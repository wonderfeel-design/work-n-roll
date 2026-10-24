"""Tasks 4-7 offline: bot flow with a fake Telegram Bot and a fake Gemma."""
import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app import bot as b
from app import db, gemma, seed
from app.schemas import Extracted, ExtractionResult, Record

CHAT = 42
TODAY = dt.datetime.now(db.TZ).date().isoformat()


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(b, "speak", lambda text, lang: None)
    monkeypatch.setattr(b, "VOICE_REPLIES", True)
    monkeypatch.delenv("AGRONOMIST_CHAT_ID", raising=False)
    db.init_db()
    seed.seed()


class FakeBot:
    def __init__(self):
        self.sent = []      # (chat_id, text, reply_markup)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append((chat_id, text, reply_markup))

    async def send_voice(self, chat_id, voice, **kw):
        self.sent.append((chat_id, "<voice>", None))

    async def send_chat_action(self, *a, **kw):
        pass


class FakeMessage:
    def __init__(self, bot, text):
        self.bot, self.text, self.voice, self.audio = bot, text, None, None
        self.chat = SimpleNamespace(id=CHAT)
        self.from_user = SimpleNamespace(language_code="en")
        self.message_id = 1

    async def answer(self, text, **kw):
        await self.bot.send_message(CHAT, text, **kw)


class FakeCallback:
    def __init__(self, bot, data):
        self.data = data
        self.message = FakeMessage(bot, None)
        self.message.edit_reply_markup = self._noop

    async def _noop(self, **kw):
        pass

    async def answer(self, *a, **kw):
        pass


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(b.ChatActionSender, "typing", lambda **kw: _NullCtx())
    bot = FakeBot()
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=CHAT, user_id=CHAT))
    return bot, state


class _NullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def run(coro):
    return asyncio.run(coro)


def _ext(**kw) -> Extracted:
    base = dict(lang="en", activity_key="treatment", date=TODAY, product="copper", quantity=40, unit="L")
    return Extracted(**(base | kw))


def test_card_shows_resolved_values_in_farmer_language():
    rid = db.insert_record(Record(lang="ca", activity_key="treatment", farmer_chat_id=CHAT, date="2026-10-23",
                                  parcel_alias="P3", product="coure", quantity=4, unit="kg",
                                  transcript_original="..."))
    card = b.render_card(db.get_record(rid))
    assert "Nou registre" in card and "25-120-0-0-8-12-1" in card
    assert "Perera" in card and "Tractament fitosanitari" in card
    assert "Dosi: 2 kg/ha" in card and "Superfície: 2 ha" in card
    kb = b.card_keyboard(rid, "ca").inline_keyboard[0]
    assert [x.callback_data for x in kb] == [f"ok:{rid}", f"edit:{rid}", f"del:{rid}"]
    assert kb[0].text == "✅ Correcte"


def test_missing_parcel_question_then_card_then_confirm(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(gemma, "extract", lambda *a: ExtractionResult(records=[_ext(missing_fields=["parcel_alias"])],
                                                                       is_farm_activity=True))
    monkeypatch.setattr(gemma, "merge", lambda cur, text: cur.model_copy(update={"parcel_alias": "P3"}))

    run(b.on_note(FakeMessage(bot, "Sprayed copper today, 40 litres"), bot, state))
    assert bot.sent[-1][1] == "Which parcel?" and bot.sent[-1][2] is not None   # parcel buttons
    assert run(state.get_state()) == b.FollowUp.answer.state
    assert db.list_records() == []

    run(b.on_followup_answer(FakeMessage(bot, "parcel 3"), bot, state))
    rec = db.list_records()[0]
    assert rec.parcel_alias == "P3" and rec.status == "draft" and rec.missing_fields == []
    assert "New record" in bot.sent[-1][1] and run(state.get_state()) is None

    run(b.on_ok(FakeCallback(bot, f"ok:{rec.id}"), bot))
    rec = db.get_record(rec.id)
    assert rec.confirmed_by == "farmer" and rec.judge_score is not None
    assert rec.status == "needs_review"          # 40 L on 2 ha = 20 L/ha, outside the demo range
    assert bot.sent[-1][1] == "Saved. Thank you!"


def test_parcel_button_answers_the_question(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(gemma, "extract", lambda *a: ExtractionResult(
        records=[_ext(quantity=4, unit="kg")], is_farm_activity=True))
    run(b.on_note(FakeMessage(bot, "copper today 4 kg"), bot, state))
    run(b.on_parcel_button(FakeCallback(bot, "fp:P3"), bot, state))
    rec = db.list_records()[0]
    assert rec.parcel_alias == "P3"
    run(b.on_ok(FakeCallback(bot, f"ok:{rec.id}"), bot))
    assert db.get_record(rec.id).status == "auto_approved"


def test_gives_up_asking_after_two_rounds(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(gemma, "extract", lambda *a: ExtractionResult(records=[_ext()], is_farm_activity=True))
    monkeypatch.setattr(gemma, "merge", lambda cur, text: cur)
    run(b.on_note(FakeMessage(bot, "copper 40 L"), bot, state))
    run(b.on_followup_answer(FakeMessage(bot, "mmm"), bot, state))
    assert db.list_records() == []
    run(b.on_followup_answer(FakeMessage(bot, "mmm"), bot, state))
    rec = db.list_records()[0]
    assert rec.parcel_alias is None and rec.missing_fields == ["parcel_alias"]


def test_several_activities_make_several_cards(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(gemma, "extract", lambda *a: ExtractionResult(records=[
        _ext(parcel_alias="P3", quantity=4, unit="kg"),
        _ext(activity_key="irrigation", parcel_alias="P2", product=None, quantity=120, unit="m3")],
        is_farm_activity=True))
    run(b.on_note(FakeMessage(bot, "..."), bot, state))
    assert len(db.list_records()) == 2
    assert bot.sent[0][1] == "2 records found"


def test_not_farm_activity(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(gemma, "extract", lambda *a: ExtractionResult(records=[], is_farm_activity=False))
    run(b.on_note(FakeMessage(bot, "hello"), bot, state))
    assert "didn't find any field work" in bot.sent[-1][1]


def test_edit_flow_changes_quantity_and_logs_correction(env, monkeypatch):
    bot, state = env
    rid = db.insert_record(Record(**_ext(parcel_alias="P5", lang="es", unit="kg").model_dump(),
                                  farmer_chat_id=CHAT, transcript_original="Catorce kilos de cobre"))
    monkeypatch.setattr(gemma, "merge", lambda cur, text: cur.model_copy(update={"quantity": 14.0}))

    run(b.on_edit(FakeCallback(bot, f"edit:{rid}"), bot, state))
    assert bot.sent[-1][1] == db.ui("ask_fix", "es")
    run(b.on_fix(FakeMessage(bot, "no, it was 14 not 40"), bot, state))
    assert db.get_record(rid).quantity == 14
    (c,) = db.corrections_for(rid)
    assert (c["field"], c["before"], c["after"], c["corrected_by"]) == ("quantity", "40", "14", "farmer")
    assert c["reason"] == "farmer edit: no, it was 14 not 40"
    assert "Nuevo registro" in bot.sent[-1][1] and "14 kg" in bot.sent[-1][1]
    assert run(state.get_state()) is None


def test_discard(env):
    bot, state = env
    rid = db.insert_record(Record(**_ext(parcel_alias="P3").model_dump(), farmer_chat_id=CHAT,
                                  transcript_original="x"))
    run(b.on_discard(FakeCallback(bot, f"del:{rid}"), bot))
    assert db.get_record(rid).status == "discarded" and bot.sent[-1][1] == "Discarded."


def test_other_farmers_buttons_are_ignored(env):
    bot, state = env
    rid = db.insert_record(Record(**_ext(parcel_alias="P3").model_dump(), farmer_chat_id=999,
                                  transcript_original="x"))
    run(b.on_ok(FakeCallback(bot, f"ok:{rid}"), bot))
    assert db.get_record(rid).status == "draft"


def test_agronomist_notified_on_needs_review(env, monkeypatch):
    bot, state = env
    monkeypatch.setenv("AGRONOMIST_CHAT_ID", "777")
    rid = db.insert_record(Record(**_ext(parcel_alias="P5", unit="kg").model_dump(), farmer_chat_id=CHAT,
                                  transcript_original="Cuarenta kilos de cobre"))
    run(b.on_ok(FakeCallback(bot, f"ok:{rid}"), bot))
    (msg,) = [t for c, t, _ in bot.sent if c == 777]
    assert f"Needs review #{rid}" in msg and "dose" in msg


def test_expert_change_message_once():
    rid = db.insert_record(Record(**_ext(parcel_alias="P5", lang="es", unit="kg").model_dump(),
                                  farmer_chat_id=CHAT, transcript_original="x"))
    seen: set[int] = set()
    assert b.expert_changes(seen) == []
    db.update_field(rid, "quantity", 14, reason="catorce", by="agronomist")
    assert b.expert_changes(seen) == [(CHAT, "Tu técnico ha cambiado Cantidad: 40 → 14")]
    assert b.expert_changes(seen) == []


def test_failed_transcription_answers_not_understood(env, monkeypatch, tmp_path):
    bot, state = env

    def boom(path):
        raise RuntimeError("Scribe failed")

    async def download(media, destination):
        pass

    monkeypatch.setattr(b, "transcribe", boom)
    monkeypatch.setattr(b, "AUDIO_DIR", tmp_path)
    bot.download = download
    msg = FakeMessage(bot, None)
    msg.voice = object()
    run(b.on_note(msg, bot, state))
    assert bot.sent[-1][1] == db.ui("not_understood", "en")
    assert db.list_records() == []


def test_note_sent_instead_of_name_is_handled_as_note(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(gemma, "extract", lambda *a: ExtractionResult(
        records=[_ext(activity_key="irrigation", parcel_alias="P2", product=None, quantity=120, unit="m3")],
        is_farm_activity=True))
    run(b.on_start(FakeMessage(bot, "/start"), bot, state))
    assert run(state.get_state()) == b.Onboarding.name.state
    run(b.on_name(FakeMessage(bot, "Watered the Gala block today, about 120 cubic metres."), bot, state))
    assert (db.get_farmer(CHAT) or {}).get("name") is None
    assert len(db.list_records()) == 1 and "New record" in bot.sent[-1][1]


def test_real_name_is_stored(env):
    bot, state = env
    run(b.on_start(FakeMessage(bot, "/start"), bot, state))
    run(b.on_name(FakeMessage(bot, "Joan Puig"), bot, state))
    assert db.get_farmer(CHAT)["name"] == "Joan Puig" and run(state.get_state()) is None


def test_no_tts_call_without_ffmpeg(env, monkeypatch):
    bot, state = env
    calls = []
    monkeypatch.setattr(b, "speak", lambda text, lang: calls.append(text) or "x.ogg")
    monkeypatch.setattr(b, "VOICE_REPLIES", False)
    run(b.say(bot, CHAT, "Saved.", "en"))
    assert calls == [] and [t for _, t, _ in bot.sent] == ["Saved."]


def test_voice_sent_when_available(env, monkeypatch):
    bot, state = env
    monkeypatch.setattr(b, "speak", lambda text, lang: "x.ogg")
    run(b.say(bot, CHAT, "Saved.", "en"))
    assert [t for _, t, _ in bot.sent] == ["Saved.", "<voice>"]


def test_start_with_known_name_sends_welcome(env):
    bot, state = env
    db.set_farmer_name(CHAT, "Joan")
    db.set_farmer_lang(CHAT, "ca")
    run(b.on_start(FakeMessage(bot, "/start"), bot, state))
    assert bot.sent[-1][1].startswith("Hola Joan!") and "Perera" in bot.sent[-1][1]


def test_name_then_welcome_and_help(env):
    bot, state = env
    run(b.on_start(FakeMessage(bot, "/start"), bot, state))
    assert bot.sent[-1][1] == db.ui("ask_name", "en")
    run(b.on_name(FakeMessage(bot, "Tom"), bot, state))
    welcome = bot.sent[-1][1]
    assert welcome.startswith("Hi Tom!")
    msg = FakeMessage(bot, "/help")
    msg.from_user.first_name = "Tommy"
    run(b.on_help(msg, bot))
    assert bot.sent[-1][1] == welcome          # same message, stored name wins
