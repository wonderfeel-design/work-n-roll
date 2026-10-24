"""Welcome message on /start and /help (built without Telegram)."""
import datetime as dt

import pytest

from app import bot as b
from app import db, seed
from app.schemas import Record

CHAT = 42
CROPS = {
    "ca": ["Presseguer", "Pomera", "Perera", "Olivera", "Ametller"],
    "ru": ["Персик", "Яблоня", "Груша", "Олива", "Миндаль"],
}
KEYS = ("start_hello", "start_parcels", "start_today", "start_functions", "func_voice", "func_confirm",
        "func_report", "func_help", "start_example")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    seed.seed()


def _today() -> dt.date:
    return dt.datetime.now(db.TZ).date()


def test_all_keys_seeded_in_every_language():
    for key in KEYS:
        for lang in ("en", "ca", "es", "ru"):
            assert db.ui(key, lang) != db.ui(key, "en") or lang == "en", f"{key} has no {lang} text"


@pytest.mark.parametrize("lang,date_fmt", [("ca", "%d/%m/%Y"), ("ru", "%d.%m.%Y")])
def test_welcome_text(lang, date_fmt):
    text = b.welcome_text(CHAT, lang, "Joan")
    lines = text.split("\n")
    assert lines[0] == db.ui("start_hello", lang).format(name="Joan", date=_today().strftime(date_fmt))
    assert lines[2] == db.ui("start_parcels", lang).format(campaign="2026")
    parcel_lines = lines[3:8]
    for line, alias, crop in zip(parcel_lines, ["P1", "P2", "P3", "P4", "P5"], CROPS[lang]):
        assert f" {alias} · {crop} · " in line and line.endswith(" ha")
    assert parcel_lines[0] == "🍑 P1 · " + CROPS[lang][0] + " · 2.40 ha"
    assert lines[8] == "" and lines[-1] == db.ui("start_example", lang)
    assert db.ui("func_report", lang) not in text            # no /report command yet
    assert "{" not in text and "}" not in text                # every placeholder filled
    for key in ("start_today", "start_functions", "func_voice", "func_confirm", "func_help"):
        assert db.ui(key, lang).split("{")[0] in text         # localized line present, not a fallback


def test_report_line_shown_once_report_exists(monkeypatch):
    monkeypatch.setattr(b, "HAS_REPORT", True)
    assert db.ui("func_report", "ca") in b.welcome_text(CHAT, "ca", "Joan")


def test_records_today_counts_own_non_discarded():
    def rec(chat, **kw):
        return db.insert_record(Record(lang="en", activity_key="irrigation", farmer_chat_id=chat,
                                       parcel_alias="P2", quantity=120, unit="m3", transcript_original="x", **kw))
    rec(CHAT)
    rec(CHAT)
    db.update_status(rec(CHAT), "discarded")
    rec(999)
    assert b.records_today(CHAT) == 2
    assert db.ui("start_today", "en").format(n=2) in b.welcome_text(CHAT, "en", "Tom")


@pytest.mark.parametrize("stored,telegram,want", [(None, "ru-RU", "ru"), (None, "ca", "ca"), (None, "de", "en"),
                                                 (None, None, "en"), ("es", "ru-RU", "es")])
def test_language_choice(stored, telegram, want):
    if stored:
        db.set_farmer_lang(CHAT, stored)
    assert b.farmer_lang(CHAT, telegram) == want
