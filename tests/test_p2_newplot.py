"""Adding plots: Gemma parsing, the bot's /newplot flow and keyword start. Offline (fake Gemma, fake Telegram)."""
import asyncio

import pytest

from app import bot as b
from app import db, gemma, seed
from app.schemas import ParcelDraft
from tests.test_p1_bot import FakeBot, FakeCallback, FakeMessage, _NullCtx  # reuse Person 1's fakes

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

CHAT = 42
CHERRY = ('{"lang": "en", "spoken_names": ["the cherry trees"], "crop_key": "cherry", '
          '"crop_labels": {"en": "Cherry", "ca": "Cirerer", "es": "Cerezo", "ru": "Вишня"}, '
          '"area_ha": 1.5, "irrigation": "regadiu", "missing_fields": []}')


@pytest.fixture(autouse=True)
def reference(monkeypatch):
    seed.seed()
    monkeypatch.setattr(b, "speak", lambda text, lang: None)
    monkeypatch.setattr(b, "VOICE_REPLIES", True)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(b.ChatActionSender, "typing", lambda **kw: _NullCtx())
    bot = FakeBot()
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=CHAT, user_id=CHAT))
    return bot, state


def _gemma_replies(monkeypatch, *replies):
    """Each parse_parcel call gets the next raw model reply."""
    queue = list(replies)
    monkeypatch.setattr(gemma, "_generate", lambda *a: queue.pop(0))


def run(coro):
    return asyncio.run(coro)


# --- gemma.parse_parcel --------------------------------------------------------

def test_parse_parcel_recomputes_missing_and_keeps_current(monkeypatch):
    _gemma_replies(monkeypatch, '{"lang": "en", "spoken_names": ["the cherry trees"], "crop_key": null,'
                                ' "area_ha": null, "missing_fields": []}',
                   '{"lang": "en", "spoken_names": [], "crop_key": "cherry", "area_ha": 1.5,'
                   ' "crop_labels": {"en": "Cherry"}, "missing_fields": []}')
    first = gemma.parse_parcel("new plot, the cherry trees", "en")
    assert first.missing_fields == ["crop_key", "area_ha"]           # not trusted from the model
    second = gemma.parse_parcel("cherries, one and a half hectares", "en", first)
    assert second.spoken_names == ["the cherry trees"] and second.area_ha == 1.5 and second.missing_fields == []


def test_parse_parcel_drops_labels_for_a_known_crop(monkeypatch):
    _gemma_replies(monkeypatch, '{"lang": "ca", "spoken_names": ["les pomeres noves"], "crop_key": "apple",'
                                ' "crop_labels": {"en": "Apple"}, "area_ha": 2}')
    d = gemma.parse_parcel("nova parcel·la: les pomeres noves, pomeres, 2 hectàrees", "ca")
    assert (d.crop_key, d.crop_labels, d.lang) == ("apple", None, "ca")


def test_parcel_prompt_lists_plots_and_crops():
    p = gemma.build_parcel_prompt("x", "es", None)
    assert "P5: crop almond" in p and "- almond: Almond" in p and "null" in p


# --- bot flow ------------------------------------------------------------------

def test_newplot_command_card_and_confirm(monkeypatch, env):
    bot, state = env
    _gemma_replies(monkeypatch, CHERRY)
    msg = FakeMessage(bot, "/newplot the cherry trees, cherry, 1.5 ha, irrigated")
    run(b.on_newplot(msg, bot, state, b.CommandObject(prefix="/", command="newplot",
                                                      args="the cherry trees, cherry, 1.5 ha, irrigated")))
    card = next(t for _, t, markup in bot.sent if markup is not None)
    assert "New plot" in card and "the cherry trees" in card and "Cherry (new crop)" in card and "1.5 ha" in card
    run(b.on_plot_ok(FakeCallback(bot, "np_ok"), bot, state))
    assert bot.sent[-1][1] == "Plot P6 added. You can log work on it now."
    p6 = next(p for p in db.get_parcels() if p["alias"] == "P6")
    assert (p6["crop_key"], p6["irrigation"]) == ("cherry", "regadiu") and db.label("crop", "cherry", "ru") == "Вишня"
    assert run(state.get_state()) is None


def test_keyword_start_asks_for_missing_then_completes(monkeypatch, env):
    bot, state = env
    _gemma_replies(monkeypatch,
                   '{"lang": "en", "spoken_names": ["the cherry trees"], "crop_key": "cherry",'
                   ' "crop_labels": {"en": "Cherry"}, "area_ha": null}',
                   CHERRY)
    run(b.on_note(FakeMessage(bot, "New plot: the cherry trees, cherries"), bot, state))
    assert bot.sent[-1][1] == "I still need: Area."
    assert run(state.get_state()) == b.NewPlot.describe.state
    run(b.on_plot_description(FakeMessage(bot, "one and a half hectares"), bot, state))
    assert run(state.get_state()) == b.NewPlot.confirm.state


def test_gives_up_after_two_questions(monkeypatch, env):
    bot, state = env
    nothing = '{"lang": "en", "spoken_names": [], "crop_key": null, "area_ha": null}'
    _gemma_replies(monkeypatch, nothing, nothing, nothing)
    run(b.start_plot(bot, CHAT, state, "something", None))
    run(b.on_plot_description(FakeMessage(bot, "hm"), bot, state))
    run(b.on_plot_description(FakeMessage(bot, "hm"), bot, state))
    assert bot.sent[-1][1].startswith("I couldn't get the name, crop and size")
    assert run(state.get_state()) is None and len(db.get_parcels()) == 5


def test_name_already_taken_is_explained(monkeypatch, env):
    bot, state = env
    _gemma_replies(monkeypatch, '{"lang": "ca", "spoken_names": ["les peres"], "crop_key": "pear", "area_ha": 1}')
    run(b.start_plot(bot, CHAT, state, "les peres, perera, una hectàrea", None))
    run(b.on_plot_ok(FakeCallback(bot, "np_ok"), bot, state))
    assert bot.sent[-1][1] == "«les peres» ja és el nom de P3. Envia /newplot de nou amb un altre nom."
    assert len(db.get_parcels()) == 5


def test_discard_saves_nothing(monkeypatch, env):
    bot, state = env
    _gemma_replies(monkeypatch, CHERRY)
    run(b.start_plot(bot, CHAT, state, "the cherry trees, cherry, 1.5 ha", None))
    run(b.on_plot_discard(FakeCallback(bot, "np_del"), state))
    assert bot.sent[-1][1] == "Discarded." and len(db.get_parcels()) == 5


def test_normal_notes_still_go_to_the_field_log(monkeypatch, env):
    bot, state = env
    seen = []
    async def fake_handle(message, bot_, state_, text, hint):
        seen.append(text)
    monkeypatch.setattr(b, "handle_note", fake_handle)
    run(b.on_note(FakeMessage(bot, "Today I watered parcel 2, 120 cubic metres"), bot, state))
    assert seen == ["Today I watered parcel 2, 120 cubic metres"]


def test_help_lists_newplot():
    db.set_farmer_name(CHAT, "Joan")
    assert "/newplot" in b.welcome_text(CHAT, "en", "Joan")
