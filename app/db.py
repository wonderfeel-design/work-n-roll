"""Shared PostgreSQL store (section 4.2 of the CLAUDE files). The bot and the web process, on any machine,
connect to the same database through DATABASE_URL. Only touch the database through these functions.

Correction rules, enforced here and by the schema:
- every change to a stored record goes through update_field, which writes the new value and a
  corrections row in one transaction;
- corrections.record_id is a foreign key to field_log.id; a correction needs a non-empty reason,
  a known field and a real change (before != after);
- corrections are append-only (only used_as_fewshot may be toggled) and records are never
  deleted: discard them instead;
- status moves only along schemas.STATUS_TRANSITIONS, and "corrected" needs a correction.

Values come back in the same shapes as before the move from SQLite: dates and timestamps as ISO
strings (Europe/Madrid), corrections.before / after as text, used_as_fewshot as 0 / 1.
"""
import datetime as dt
import json
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.schemas import (
    ACTIVITIES,
    CORRECTORS,
    EDITABLE_FIELDS,
    LANGS,
    STATUS_TRANSITIONS,
    STATUSES,
    Record,
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fieldvoice@localhost:5432/fieldvoice")
SCHEMA_NAME = os.getenv("DB_SCHEMA", "public")  # tests use a throwaway schema each
TZ = ZoneInfo(os.getenv("TZ_NAME", "Europe/Madrid"))
DB_PATH = None  # SQLite leftover: older tests still monkeypatch it; it has no effect

IntegrityError = psycopg.IntegrityError  # what callers catch for constraint violations


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS vocabulary (
    key  TEXT NOT NULL,
    type TEXT NOT NULL,                       -- activity | crop | pest | any
    en TEXT, ca TEXT, es TEXT, ru TEXT,
    PRIMARY KEY (type, key)
);
CREATE TABLE IF NOT EXISTS ui_strings (
    key TEXT PRIMARY KEY,
    en  TEXT NOT NULL,
    ca TEXT, es TEXT, ru TEXT
);
CREATE TABLE IF NOT EXISTS parcels (
    alias TEXT PRIMARY KEY,                   -- P1..P5
    spoken_names TEXT NOT NULL,               -- '; ' separated, all languages
    campaign TEXT, explotacio_id TEXT,
    sigpac_prov INTEGER, sigpac_mun INTEGER, sigpac_agregat INTEGER, sigpac_zona INTEGER,
    sigpac_poligon INTEGER, sigpac_parcela INTEGER, sigpac_recinte INTEGER,
    sigpac_ref TEXT NOT NULL,
    sigpac_use TEXT,
    crop_key TEXT NOT NULL,
    variety TEXT,
    area_ha DOUBLE PRECISION NOT NULL CHECK (area_ha > 0),
    irrigation TEXT, tenure TEXT, eco_scheme TEXT
);
CREATE TABLE IF NOT EXISTS farmers (
    chat_id BIGINT PRIMARY KEY,
    name TEXT,
    last_lang TEXT CHECK (last_lang IS NULL OR last_lang IN {_in(LANGS)})
);
CREATE TABLE IF NOT EXISTS field_log (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lang TEXT NOT NULL CHECK (lang IN {_in(LANGS)}),
    date DATE,
    date_spoken TEXT,
    parcel_spoken TEXT,
    parcel_alias TEXT REFERENCES parcels(alias),
    crop_spoken TEXT,
    activity_key TEXT NOT NULL CHECK (activity_key IN {_in(ACTIVITIES)}),
    product TEXT,
    target_pest_key TEXT,
    quantity DOUBLE PRECISION CHECK (quantity IS NULL OR quantity >= 0),
    unit TEXT,
    area_ha DOUBLE PRECISION CHECK (area_ha IS NULL OR area_ha > 0),
    notes_ca TEXT,
    notes_en TEXT,
    missing_fields JSONB NOT NULL DEFAULT '[]',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    farmer_chat_id BIGINT NOT NULL REFERENCES farmers(chat_id),
    farmer_name TEXT,
    transcript_original TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN {_in(STATUSES)}),
    judge_score DOUBLE PRECISION CHECK (judge_score IS NULL OR judge_score BETWEEN 0 AND 1),
    judge_reason TEXT,
    confirmed_by TEXT,
    corrected_by TEXT CHECK (corrected_by IS NULL OR corrected_by IN {_in(CORRECTORS)}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES field_log(id) ON DELETE RESTRICT,
    field TEXT NOT NULL CHECK (field IN {_in(EDITABLE_FIELDS)}),
    before TEXT,
    after TEXT,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    reason_lang TEXT CHECK (reason_lang IS NULL OR reason_lang IN {_in(LANGS)}),
    corrected_by TEXT NOT NULL CHECK (corrected_by IN {_in(CORRECTORS)}),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_as_fewshot BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (before IS DISTINCT FROM after)
);
CREATE INDEX IF NOT EXISTS corrections_record ON corrections(record_id);

-- Raised as SQLSTATE 23000 so clients see an IntegrityError, like the other constraints
CREATE OR REPLACE FUNCTION fv_forbid() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION USING ERRCODE = '23000', MESSAGE = TG_ARGV[0]; END $$;

CREATE OR REPLACE TRIGGER corrections_no_delete BEFORE DELETE ON corrections
FOR EACH ROW EXECUTE FUNCTION fv_forbid('corrections are append-only');
CREATE OR REPLACE TRIGGER corrections_no_update
BEFORE UPDATE OF record_id, field, before, after, reason, reason_lang, corrected_by, timestamp ON corrections
FOR EACH ROW EXECUTE FUNCTION fv_forbid('corrections are append-only');
CREATE OR REPLACE TRIGGER field_log_no_delete BEFORE DELETE ON field_log
FOR EACH ROW EXECUTE FUNCTION fv_forbid('records are never deleted: set status to discarded');
"""

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL, min_size=1, max_size=8, open=True, timeout=10,
            kwargs={"row_factory": dict_row, "options": f"-c search_path={SCHEMA_NAME} -c TimeZone={TZ.key}"},
        )
    return _pool


def use(url: str | None = None, schema: str | None = None) -> None:
    """Point this process at another database or schema (tests). Closes the current pool."""
    global _pool, DATABASE_URL, SCHEMA_NAME
    if _pool is not None:
        _pool.close()
        _pool = None
    DATABASE_URL = url or DATABASE_URL
    SCHEMA_NAME = schema or SCHEMA_NAME


@contextmanager
def _connect() -> Iterator[psycopg.Connection]:
    """One transaction: commit on success, roll back on error."""
    with _get_pool().connection() as conn:
        yield conn


def _now() -> dt.datetime:
    return dt.datetime.now(TZ)


def _iso(v: Any) -> Any:
    """Postgres date / timestamp -> the ISO strings callers had with SQLite."""
    if isinstance(v, dt.datetime):
        return v.astimezone(TZ).isoformat(timespec="seconds")
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _text(v: Any) -> Optional[str]:
    """How values appear in corrections.before / after."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def init_db() -> None:
    """Create the schema if needed. Safe when seed, web and bot start at the same time."""
    with _connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(4242)")  # one creator at a time
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(SCHEMA_NAME)))
        conn.execute(SCHEMA)


# --- field_log ---------------------------------------------------------------

_RECORD_COLUMNS = tuple(f for f in Record.model_fields if f != "id")


def _row_to_record(row: dict) -> Record:
    data = {k: _iso(v) for k, v in row.items() if k in Record.model_fields}
    return Record.model_validate(data)


def insert_record(rec: Record) -> int:
    """Store a new record. It must be a draft without an id; the farmer row is created if needed."""
    if rec.id is not None:
        raise ValueError("insert_record assigns the id; pass a Record with id=None")
    if rec.status != "draft":
        raise ValueError("new records start as draft; use update_status to move them on")
    now = _now()
    values = rec.model_dump(include=set(_RECORD_COLUMNS))
    values.update(missing_fields=json.dumps(rec.missing_fields), created_at=now, updated_at=now)
    cols = list(values)
    with _connect() as conn:
        conn.execute("INSERT INTO farmers (chat_id, name) VALUES (%s, %s) ON CONFLICT (chat_id) DO NOTHING",
                     (rec.farmer_chat_id, rec.farmer_name))
        row = conn.execute(
            sql.SQL("INSERT INTO field_log ({}) VALUES ({}) RETURNING id").format(
                sql.SQL(", ").join(map(sql.Identifier, cols)), sql.SQL(", ").join(sql.Placeholder() * len(cols))),
            [values[c] for c in cols],
        ).fetchone()
        return row["id"]


def get_record(id: int) -> Record:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM field_log WHERE id = %s", (id,)).fetchone()
    if row is None:
        raise KeyError(f"no record {id}")
    return _row_to_record(row)


def list_records(limit: int = 200) -> list[Record]:
    """Newest first."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM field_log ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    return [_row_to_record(r) for r in rows]


def update_status(id: int, status: str, by: str | None = None) -> None:
    """Move a record along STATUS_TRANSITIONS. "farmer_confirmed" records confirmed_by."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with _connect() as conn:
        row = conn.execute("SELECT status FROM field_log WHERE id = %s FOR UPDATE", (id,)).fetchone()
        if row is None:
            raise KeyError(f"no record {id}")
        current = row["status"]
        if status not in STATUS_TRANSITIONS[current]:
            raise ValueError(f"status cannot go from {current} to {status}")
        if status == "corrected" and not conn.execute(
            "SELECT 1 FROM corrections WHERE record_id = %s AND corrected_by = 'agronomist'", (id,)
        ).fetchone():
            raise ValueError("status 'corrected' needs an agronomist correction (update_field) first")
        if status == "farmer_confirmed" and by:
            conn.execute("UPDATE field_log SET status = %s, confirmed_by = %s, updated_at = %s WHERE id = %s",
                         (status, by, _now(), id))
        else:
            conn.execute("UPDATE field_log SET status = %s, updated_at = %s WHERE id = %s", (status, _now(), id))


def set_judge(id: int, score: float, reason: str) -> None:
    """Store the validator's judge_score (0-1) and one-line judge_reason. Not a correction."""
    if not 0.0 <= score <= 1.0:
        raise ValueError("judge_score must be between 0 and 1")
    with _connect() as conn:
        cur = conn.execute("UPDATE field_log SET judge_score = %s, judge_reason = %s, updated_at = %s WHERE id = %s",
                           (score, reason, _now(), id))
        if cur.rowcount == 0:
            raise KeyError(f"no record {id}")


def update_field(id: int, field: str, value: Any, reason: str, by: str,
                 reason_lang: str | None = None) -> None:
    """Change one field and log it to corrections in the same transaction.

    Raises ValueError for a field outside EDITABLE_FIELDS, an unknown corrector, an empty reason,
    a value that fails Record validation, no actual change, or a discarded record.
    IntegrityError (e.g. a parcel that doesn't exist) rolls the whole change back.
    """
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"field {field!r} cannot be corrected; allowed: {', '.join(EDITABLE_FIELDS)}")
    if by not in CORRECTORS:
        raise ValueError(f"corrected_by must be one of {CORRECTORS}")
    if not (reason or "").strip():
        raise ValueError("a correction needs a reason")
    if isinstance(value, str):
        value = value.strip() or None

    rec = get_record(id)
    if rec.status == "discarded":
        raise ValueError("discarded records cannot be corrected")
    new = Record.model_validate({**rec.model_dump(), field: value})  # coerces "14" -> 14.0, checks dates
    before, after = getattr(rec, field), getattr(new, field)
    if before == after:
        raise ValueError(f"{field} is already {after!r}")

    with _connect() as conn:
        conn.execute(
            sql.SQL("UPDATE field_log SET {} = %s, corrected_by = %s, updated_at = %s WHERE id = %s").format(
                sql.Identifier(field)),
            (after, by, _now(), id),
        )
        conn.execute(
            "INSERT INTO corrections (record_id, field, before, after, reason, reason_lang, corrected_by, timestamp)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (id, field, _text(before), _text(after), reason.strip(), reason_lang, by, _now()),
        )


# --- corrections -------------------------------------------------------------

_CORRECTION_SELECT = """
SELECT c.*, f.transcript_original, f.lang
FROM corrections c JOIN field_log f ON f.id = c.record_id
"""


def _correction(row: dict) -> dict:
    return {**row, "timestamp": _iso(row["timestamp"]), "used_as_fewshot": int(row["used_as_fewshot"])}


def recent_corrections(n: int = 5) -> list[dict]:
    """Newest first, only rows marked for few-shot use, with the record's transcript and lang."""
    with _connect() as conn:
        rows = conn.execute(_CORRECTION_SELECT + " WHERE c.used_as_fewshot ORDER BY c.id DESC LIMIT %s",
                            (n,)).fetchall()
    return [_correction(r) for r in rows]


def corrections_for(record_id: int) -> list[dict]:
    """All corrections of one record, oldest first."""
    with _connect() as conn:
        rows = conn.execute(_CORRECTION_SELECT + " WHERE c.record_id = %s ORDER BY c.id", (record_id,)).fetchall()
    return [_correction(r) for r in rows]


def set_fewshot(correction_id: int, used: bool) -> None:
    """The only change allowed on a stored correction."""
    with _connect() as conn:
        conn.execute("UPDATE corrections SET used_as_fewshot = %s WHERE id = %s", (bool(used), correction_id))


# --- reference data ------------------------------------------------------------

def get_parcels() -> list[dict]:
    """alias, spoken_names (list), crop_key, area_ha, sigpac_ref and the other DUN columns."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM parcels ORDER BY alias").fetchall()
    return [{**r, "spoken_names": [s.strip() for s in r["spoken_names"].split(";") if s.strip()]} for r in rows]


def get_vocabulary() -> list[dict]:
    """key, type, en, ca, es, ru"""
    with _connect() as conn:
        return conn.execute("SELECT key, type, en, ca, es, ru FROM vocabulary ORDER BY type, key").fetchall()


def label(type: str, key: str | None, lang: str) -> str | None:
    """Vocabulary label for a key in one language, falling back to English, then to the key."""
    if key is None:
        return None
    if lang not in LANGS:
        raise ValueError(f"unknown lang {lang!r}")
    with _connect() as conn:
        row = conn.execute(
            sql.SQL("SELECT {} AS label, en FROM vocabulary WHERE type IN (%s, 'any') AND key = %s").format(
                sql.Identifier(lang)), (type, key)).fetchone()
    return (row["label"] or row["en"] or key) if row else key


def ui(key: str, lang: str) -> str:
    """UI string in the farmer's language, falling back to English. Unknown keys raise KeyError."""
    if lang not in LANGS:
        lang = "en"
    with _connect() as conn:
        row = conn.execute(sql.SQL("SELECT {} AS text, en FROM ui_strings WHERE key = %s").format(
            sql.Identifier(lang)), (key,)).fetchone()
    if row is None:
        raise KeyError(f"no UI string {key!r}: add it to the UI_Strings tab and re-seed")
    return row["text"] or row["en"]


# --- farmers -----------------------------------------------------------------

def set_farmer_name(chat_id: int, name: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO farmers (chat_id, name) VALUES (%s, %s)"
                     " ON CONFLICT (chat_id) DO UPDATE SET name = excluded.name", (chat_id, name))


def set_farmer_lang(chat_id: int, lang: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO farmers (chat_id, last_lang) VALUES (%s, %s)"
                     " ON CONFLICT (chat_id) DO UPDATE SET last_lang = excluded.last_lang", (chat_id, lang))


def get_farmer_lang(chat_id: int) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT last_lang FROM farmers WHERE chat_id = %s", (chat_id,)).fetchone()
    return row["last_lang"] if row else None


def get_farmer(chat_id: int) -> dict | None:
    with _connect() as conn:
        return conn.execute("SELECT * FROM farmers WHERE chat_id = %s", (chat_id,)).fetchone()
