"""Shared SQLite store (section 4.2 of the CLAUDE files). The bot and the web process open the
same file in WAL mode. Only touch the database through these functions.

Correction rules, enforced here and by the schema:
- every change to a stored record goes through update_field, which writes the new value and a
  corrections row in one transaction;
- corrections.record_id is a foreign key to field_log.id; a correction needs a non-empty reason,
  a known field and a real change (before != after);
- corrections are append-only (only used_as_fewshot may be toggled) and records are never
  deleted: discard them instead;
- status moves only along schemas.STATUS_TRANSITIONS, and "corrected" needs a correction.
"""
import datetime as dt
import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

from app import ROOT
from app.schemas import (
    ACTIVITIES,
    CORRECTORS,
    EDITABLE_FIELDS,
    LANGS,
    STATUS_TRANSITIONS,
    STATUSES,
    Record,
)

DB_PATH = ROOT / os.getenv("DB_PATH", "data/fieldvoice.db")
TZ = ZoneInfo(os.getenv("TZ_NAME", "Europe/Madrid"))


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
    area_ha REAL NOT NULL CHECK (area_ha > 0),
    irrigation TEXT, tenure TEXT, eco_scheme TEXT
);
CREATE TABLE IF NOT EXISTS farmers (
    chat_id INTEGER PRIMARY KEY,
    name TEXT,
    last_lang TEXT CHECK (last_lang IS NULL OR last_lang IN {_in(LANGS)})
);
CREATE TABLE IF NOT EXISTS field_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lang TEXT NOT NULL CHECK (lang IN {_in(LANGS)}),
    date TEXT CHECK (date IS NULL OR date(date) = date),
    date_spoken TEXT,
    parcel_spoken TEXT,
    parcel_alias TEXT REFERENCES parcels(alias),
    crop_spoken TEXT,
    activity_key TEXT NOT NULL CHECK (activity_key IN {_in(ACTIVITIES)}),
    product TEXT,
    target_pest_key TEXT,
    quantity REAL CHECK (quantity IS NULL OR quantity >= 0),
    unit TEXT,
    area_ha REAL CHECK (area_ha IS NULL OR area_ha > 0),
    notes_ca TEXT,
    notes_en TEXT,
    missing_fields TEXT NOT NULL DEFAULT '[]',   -- JSON list
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    farmer_chat_id INTEGER NOT NULL REFERENCES farmers(chat_id),
    farmer_name TEXT,
    transcript_original TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN {_in(STATUSES)}),
    judge_score REAL CHECK (judge_score IS NULL OR judge_score BETWEEN 0 AND 1),
    judge_reason TEXT,
    confirmed_by TEXT,
    corrected_by TEXT CHECK (corrected_by IS NULL OR corrected_by IN {_in(CORRECTORS)}),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES field_log(id) ON DELETE RESTRICT,
    field TEXT NOT NULL CHECK (field IN {_in(EDITABLE_FIELDS)}),
    before TEXT,
    after TEXT,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    reason_lang TEXT CHECK (reason_lang IS NULL OR reason_lang IN {_in(LANGS)}),
    corrected_by TEXT NOT NULL CHECK (corrected_by IN {_in(CORRECTORS)}),
    timestamp TEXT NOT NULL,
    used_as_fewshot INTEGER NOT NULL DEFAULT 1 CHECK (used_as_fewshot IN (0, 1)),
    CHECK (before IS NOT after)
);
CREATE INDEX IF NOT EXISTS corrections_record ON corrections(record_id);

CREATE TRIGGER IF NOT EXISTS corrections_no_delete BEFORE DELETE ON corrections
BEGIN SELECT RAISE(ABORT, 'corrections are append-only'); END;
CREATE TRIGGER IF NOT EXISTS corrections_no_update
BEFORE UPDATE OF record_id, field, before, after, reason, reason_lang, corrected_by, timestamp ON corrections
BEGIN SELECT RAISE(ABORT, 'corrections are append-only'); END;
CREATE TRIGGER IF NOT EXISTS field_log_no_delete BEFORE DELETE ON field_log
BEGIN SELECT RAISE(ABORT, 'records are never deleted: set status to discarded'); END;
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:  # one transaction: commit on success, roll back on error
            yield conn
    finally:
        conn.close()


def _now() -> str:
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


def _text(v: Any) -> Optional[str]:
    """How values appear in corrections.before / after."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


# --- field_log ---------------------------------------------------------------

_RECORD_COLUMNS = tuple(f for f in Record.model_fields if f != "id")


def _row_to_record(row: sqlite3.Row) -> Record:
    data = {k: row[k] for k in row.keys() if k in Record.model_fields}
    data["missing_fields"] = json.loads(data["missing_fields"] or "[]")
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
        conn.execute("INSERT OR IGNORE INTO farmers (chat_id, name) VALUES (?, ?)",
                     (rec.farmer_chat_id, rec.farmer_name))
        cur = conn.execute(
            f"INSERT INTO field_log ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [values[c] for c in cols],
        )
        return cur.lastrowid


def get_record(id: int) -> Record:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM field_log WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise KeyError(f"no record {id}")
    return _row_to_record(row)


def list_records(limit: int = 200) -> list[Record]:
    """Newest first."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM field_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_record(r) for r in rows]


def update_status(id: int, status: str, by: str | None = None) -> None:
    """Move a record along STATUS_TRANSITIONS. "farmer_confirmed" records confirmed_by."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with _connect() as conn:
        row = conn.execute("SELECT status FROM field_log WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise KeyError(f"no record {id}")
        current = row["status"]
        if status not in STATUS_TRANSITIONS[current]:
            raise ValueError(f"status cannot go from {current} to {status}")
        if status == "corrected" and not conn.execute(
            "SELECT 1 FROM corrections WHERE record_id = ? AND corrected_by = 'agronomist'", (id,)
        ).fetchone():
            raise ValueError("status 'corrected' needs an agronomist correction (update_field) first")
        sets, args = ["status = ?", "updated_at = ?"], [status, _now()]
        if status == "farmer_confirmed" and by:
            sets.append("confirmed_by = ?")
            args.append(by)
        conn.execute(f"UPDATE field_log SET {', '.join(sets)} WHERE id = ?", (*args, id))


def update_field(id: int, field: str, value: Any, reason: str, by: str,
                 reason_lang: str | None = None) -> None:
    """Change one field and log it to corrections in the same transaction.

    Raises ValueError for a field outside EDITABLE_FIELDS, an unknown corrector, an empty reason,
    a value that fails Record validation, no actual change, or a discarded record.
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
            f"UPDATE field_log SET {field} = ?, corrected_by = ?, updated_at = ? WHERE id = ?",
            (after, by, _now(), id),
        )
        conn.execute(
            "INSERT INTO corrections (record_id, field, before, after, reason, reason_lang, corrected_by, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, field, _text(before), _text(after), reason.strip(), reason_lang, by, _now()),
        )


# --- corrections -------------------------------------------------------------

_CORRECTION_SELECT = """
SELECT c.*, f.transcript_original, f.lang
FROM corrections c JOIN field_log f ON f.id = c.record_id
"""


def recent_corrections(n: int = 5) -> list[dict]:
    """Newest first, only rows marked for few-shot use, with the record's transcript and lang."""
    with _connect() as conn:
        rows = conn.execute(
            _CORRECTION_SELECT + " WHERE c.used_as_fewshot = 1 ORDER BY c.id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def corrections_for(record_id: int) -> list[dict]:
    """All corrections of one record, oldest first."""
    with _connect() as conn:
        rows = conn.execute(_CORRECTION_SELECT + " WHERE c.record_id = ? ORDER BY c.id", (record_id,)).fetchall()
    return [dict(r) for r in rows]


def set_fewshot(correction_id: int, used: bool) -> None:
    """The only change allowed on a stored correction."""
    with _connect() as conn:
        conn.execute("UPDATE corrections SET used_as_fewshot = ? WHERE id = ?", (int(used), correction_id))


# --- reference data ------------------------------------------------------------

def get_parcels() -> list[dict]:
    """alias, spoken_names (list), crop_key, area_ha, sigpac_ref and the other DUN columns."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM parcels ORDER BY alias").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["spoken_names"] = [s.strip() for s in d["spoken_names"].split(";") if s.strip()]
        out.append(d)
    return out


def get_vocabulary() -> list[dict]:
    """key, type, en, ca, es, ru"""
    with _connect() as conn:
        rows = conn.execute("SELECT key, type, en, ca, es, ru FROM vocabulary ORDER BY type, key").fetchall()
    return [dict(r) for r in rows]


def label(type: str, key: str | None, lang: str) -> str | None:
    """Vocabulary label for a key in one language, falling back to English, then to the key."""
    if key is None:
        return None
    if lang not in LANGS:
        raise ValueError(f"unknown lang {lang!r}")
    with _connect() as conn:
        row = conn.execute(f"SELECT {lang}, en FROM vocabulary WHERE type IN (?, 'any') AND key = ?",
                           (type, key)).fetchone()
    return (row[0] or row[1] or key) if row else key


def ui(key: str, lang: str) -> str:
    """UI string in the farmer's language, falling back to English. Unknown keys raise KeyError."""
    if lang not in LANGS:
        lang = "en"
    with _connect() as conn:
        row = conn.execute(f"SELECT {lang}, en FROM ui_strings WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise KeyError(f"no UI string {key!r}: add it to the UI_Strings tab and re-seed")
    return row[0] or row[1]


# --- farmers -----------------------------------------------------------------

def set_farmer_name(chat_id: int, name: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO farmers (chat_id, name) VALUES (?, ?)"
                     " ON CONFLICT(chat_id) DO UPDATE SET name = excluded.name", (chat_id, name))


def set_farmer_lang(chat_id: int, lang: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO farmers (chat_id, last_lang) VALUES (?, ?)"
                     " ON CONFLICT(chat_id) DO UPDATE SET last_lang = excluded.last_lang", (chat_id, lang))


def get_farmer_lang(chat_id: int) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT last_lang FROM farmers WHERE chat_id = ?", (chat_id,)).fetchone()
    return row["last_lang"] if row else None


def get_farmer(chat_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM farmers WHERE chat_id = ?", (chat_id,)).fetchone()
    return dict(row) if row else None
