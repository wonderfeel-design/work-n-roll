"""Telegram bot (aiogram 3, long polling): voice/text note → Gemma → card → confirm/edit/discard.

Run: python -m app.bot
"""
import asyncio
import html
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)
from aiogram.utils.chat_action import ChatActionSender

from app import DATA_DIR, db, gemma, validator
from app.schemas import LANGS, Extracted, Record

try:
    from app.voice import speak, transcribe
except ImportError:
    from app.voice_stub import speak, transcribe   # TODO(P2): remove when voice.py lands

log = logging.getLogger(__name__)
router = Router()

AUDIO_DIR = DATA_DIR / "audio"
MAX_FOLLOWUPS = 2
POLL_SECONDS = 10

# Missing field → question asked, in this order.
QUESTIONS = {"parcel_alias": "ask_parcel", "date": "ask_date", "product": "ask_product",
             "quantity": "ask_quantity"}
# Record field → UI label key (card rows, "changed_by_expert").
FIELD_LABELS = {"date": "date", "parcel_alias": "parcel", "crop_spoken": "crop", "activity_key": "activity",
                "product": "product", "target_pest_key": "pest", "quantity": "quantity", "area_ha": "area"}


class Onboarding(StatesGroup):
    name = State()


class FollowUp(StatesGroup):
    answer = State()      # data: queue (records still to show), rounds, transcript


class Fix(StatesGroup):
    awaiting = State()    # "awaiting_fix:<id>": data record_id


# --- helpers -------------------------------------------------------------------

def farmer_lang(chat_id: int, telegram_lang: str | None = None) -> str:
    lang = db.get_farmer_lang(chat_id)
    if lang:
        return lang
    tl = (telegram_lang or "")[:2]
    return tl if tl in LANGS else "en"


def _num(v: float) -> str:
    return f"{round(v, 2):g}"


def _parcel(alias: str | None) -> dict | None:
    return next((p for p in db.get_parcels() if p["alias"] == alias), None)


def render_card(rec: Record) -> str:
    """Card text in the farmer's language with resolved values. Labels come from ui_strings."""
    lang = rec.lang
    parcel = _parcel(rec.parcel_alias)
    e = html.escape
    rows: list[tuple[str, str]] = [("date", rec.date or "—")]
    rows.append(("parcel", f"{rec.parcel_alias} · SIGPAC {parcel['sigpac_ref']}" if parcel else "—"))
    crop_key = validator.crop_key_for(rec.crop_spoken) or (parcel["crop_key"] if parcel else None)
    rows.append(("crop", db.label("crop", crop_key, lang) or rec.crop_spoken or "—"))
    rows.append(("activity", db.label("activity", rec.activity_key, lang)))
    if rec.product or rec.activity_key in ("treatment", "fertilization"):
        rows.append(("product", rec.product or "—"))
    if rec.target_pest_key and rec.target_pest_key != "none":
        rows.append(("pest", db.label("pest", rec.target_pest_key, lang)))
    rows.append(("quantity", f"{_num(rec.quantity)} {rec.unit or ''}".strip() if rec.quantity is not None else "—"))
    area = rec.area_ha or (parcel["area_ha"] if parcel else None)
    if area:
        rows.append(("area", f"{_num(area)} ha"))
    dose = validator.dose_per_ha(rec, parcel)
    if dose is not None:
        rows.append(("dose", f"{_num(dose)} {rec.unit or ''}/ha"))
    lines = [f"<b>{e(db.ui('card_title', lang))}</b>"]
    lines += [f"{e(db.ui(k, lang))}: {e(str(v))}" for k, v in rows]
    notes = rec.notes_en if lang == "en" else rec.notes_ca if lang == "ca" else None
    if notes:
        lines.append(f"<i>{e(notes)}</i>")
    return "\n".join(lines)


def card_summary(rec: Record) -> str:
    """Short sentence for the spoken card."""
    parts = [db.label("activity", rec.activity_key, rec.lang)]
    if rec.parcel_alias:
        parts.append(f"{db.ui('parcel', rec.lang)} {rec.parcel_alias[1:]}")
    if rec.product:
        parts.append(rec.product)
    if rec.quantity is not None:
        parts.append(f"{_num(rec.quantity)} {rec.unit or ''}".strip())
    return f"{db.ui('card_title', rec.lang)}: " + ", ".join(parts) + "."


def card_keyboard(rec_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=db.ui("btn_ok", lang), callback_data=f"ok:{rec_id}"),
        InlineKeyboardButton(text=db.ui("btn_edit", lang), callback_data=f"edit:{rec_id}"),
        InlineKeyboardButton(text=db.ui("btn_discard", lang), callback_data=f"del:{rec_id}"),
    ]])


def parcel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"{p['alias']} · {db.label('crop', p['crop_key'], lang)}", callback_data=f"fp:{p['alias']}")]
        for p in db.get_parcels()])


async def say(bot: Bot, chat_id: int, text: str, lang: str, **kwargs) -> None:
    """Text, plus voice when speak() can make it (None → text only)."""
    await bot.send_message(chat_id, text, **kwargs)
    try:
        path = await asyncio.to_thread(speak, html.unescape(text), lang)
    except Exception:
        log.exception("speak failed")
        path = None
    if path:
        await bot.send_voice(chat_id, FSInputFile(path))


async def send_card(bot: Bot, rec: Record) -> None:
    await bot.send_message(rec.farmer_chat_id, render_card(rec), reply_markup=card_keyboard(rec.id, rec.lang))
    try:
        path = await asyncio.to_thread(speak, card_summary(rec), rec.lang)
    except Exception:
        log.exception("speak failed")
        path = None
    if path:
        await bot.send_voice(rec.farmer_chat_id, FSInputFile(path))


async def message_text(message: Message, bot: Bot) -> tuple[str, str | None]:
    """Transcript and language hint for a text or voice message."""
    if message.voice or message.audio:
        media = message.voice or message.audio
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path = AUDIO_DIR / f"{message.chat.id}_{message.message_id}.oga"
        await bot.download(media, destination=path)
        result = await asyncio.to_thread(transcribe, str(path))
        return (result.get("text") or "").strip(), result.get("lang")
    return (message.text or "").strip(), None


def judge(rec_id: int) -> str:
    """Score a farmer-confirmed record, store the score, move it to auto_approved / needs_review."""
    rec = db.get_record(rec_id)
    score, reason = validator.validate(rec)
    db.set_judge(rec_id, score, reason)
    status = validator.status_for(score)
    if rec.status != status:
        try:
            db.update_status(rec_id, status)
        except ValueError:      # e.g. needs_review → auto_approved is not allowed: keep for review
            return rec.status
    return status


# --- note → records → follow-up questions → cards -----------------------------

async def advance(bot: Bot, chat_id: int, state: FSMContext, queue: list[dict], transcript: str,
                  rounds: int) -> None:
    """Show cards for the queued records; stop at the first one that still needs an answer."""
    farmer = db.get_farmer(chat_id) or {}
    while queue:
        cur = Extracted.model_validate(queue[0])
        missing = [f for f in validator.missing_fields(cur) if f in QUESTIONS]
        if missing and rounds < MAX_FOLLOWUPS:
            await state.set_state(FollowUp.answer)
            await state.update_data(queue=queue, rounds=rounds, transcript=transcript)
            field = missing[0]
            markup = parcel_keyboard(cur.lang) if field == "parcel_alias" else None
            await say(bot, chat_id, db.ui(QUESTIONS[field], cur.lang), cur.lang, reply_markup=markup)
            return
        queue.pop(0)
        rounds = 0
        cur.missing_fields = validator.missing_fields(cur)
        rec = Record(**cur.model_dump(), farmer_chat_id=chat_id, farmer_name=farmer.get("name"),
                     transcript_original=transcript)
        rec.id = db.insert_record(rec)
        await send_card(bot, db.get_record(rec.id))
    await state.clear()


async def handle_note(message: Message, bot: Bot, state: FSMContext, text: str, hint: str | None) -> None:
    chat_id = message.chat.id
    lang = hint or farmer_lang(chat_id, message.from_user and message.from_user.language_code)
    if not text:
        await say(bot, chat_id, db.ui("not_understood", lang), lang)
        return
    async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
        try:
            result = await asyncio.to_thread(gemma.extract, text, hint, chat_id)
        except gemma.GemmaError:
            log.exception("extract failed")
            await say(bot, chat_id, db.ui("not_understood", lang), lang)
            return
    if not result.is_farm_activity:
        await say(bot, chat_id, db.ui("not_farm_activity", lang), lang)
        return
    lang = result.records[0].lang
    db.set_farmer_lang(chat_id, lang)
    if len(result.records) > 1:
        await bot.send_message(chat_id, db.ui("records_found", lang).format(n=len(result.records)))
    await advance(bot, chat_id, state, [r.model_dump() for r in result.records], text, rounds=0)


# --- handlers ------------------------------------------------------------------

@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    lang = farmer_lang(message.chat.id, message.from_user and message.from_user.language_code)
    farmer = db.get_farmer(message.chat.id)
    if farmer and farmer.get("name"):
        await message.answer(db.ui("welcome", lang))
        return
    db.set_farmer_lang(message.chat.id, lang)
    await state.set_state(Onboarding.name)
    await message.answer(db.ui("ask_name", lang))


@router.message(Onboarding.name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    db.set_farmer_name(message.chat.id, message.text.strip()[:80])
    await state.clear()
    await message.answer(db.ui("welcome", farmer_lang(message.chat.id)))


@router.message(FollowUp.answer, F.text | F.voice | F.audio)
async def on_followup_answer(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    queue, rounds = data["queue"], data["rounds"] + 1
    text, _ = await message_text(message, bot)
    if text:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            try:
                merged = await asyncio.to_thread(gemma.merge, Extracted.model_validate(queue[0]), text)
                queue[0] = merged.model_dump()
            except gemma.GemmaError:
                log.exception("merge failed")
    await advance(bot, message.chat.id, state, queue, data["transcript"], rounds)


@router.callback_query(FollowUp.answer, F.data.startswith("fp:"))
async def on_parcel_button(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    queue = data["queue"]
    queue[0]["parcel_alias"] = cb.data.split(":", 1)[1]
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await advance(bot, cb.message.chat.id, state, queue, data["transcript"], data["rounds"] + 1)


async def _own_record(cb: CallbackQuery) -> Record | None:
    try:
        rec = db.get_record(int(cb.data.split(":", 1)[1]))
    except (KeyError, ValueError):
        rec = None
    if rec is None or rec.farmer_chat_id != cb.message.chat.id:
        await cb.answer()
        return None
    return rec


@router.callback_query(F.data.startswith("ok:"))
async def on_ok(cb: CallbackQuery, bot: Bot) -> None:
    rec = await _own_record(cb)
    if rec is None:
        return
    if rec.status == "draft":
        db.update_status(rec.id, "farmer_confirmed", "farmer")
        if judge(rec.id) == "needs_review":
            await notify_agronomist(bot, rec.id)
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await say(bot, rec.farmer_chat_id, db.ui("saved", rec.lang), rec.lang)


@router.callback_query(F.data.startswith("del:"))
async def on_discard(cb: CallbackQuery, bot: Bot) -> None:
    rec = await _own_record(cb)
    if rec is None:
        return
    if rec.status != "discarded":
        try:
            db.update_status(rec.id, "discarded")
        except ValueError:      # already validated by the agronomist
            await cb.answer()
            return
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(db.ui("discarded", rec.lang))


@router.callback_query(F.data.startswith("edit:"))
async def on_edit(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    rec = await _own_record(cb)
    if rec is None:
        return
    await state.set_state(Fix.awaiting)
    await state.update_data(record_id=rec.id)
    await cb.answer()
    await say(bot, rec.farmer_chat_id, db.ui("ask_fix", rec.lang), rec.lang)


@router.message(Fix.awaiting, F.text | F.voice | F.audio)
async def on_fix(message: Message, bot: Bot, state: FSMContext) -> None:
    rec = db.get_record((await state.get_data())["record_id"])
    words, _ = await message_text(message, bot)
    changes = {}
    if words:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            try:
                updated = await asyncio.to_thread(gemma.merge, Extracted.model_validate(rec.model_dump()), words)
                changes = gemma.changed_fields(rec, updated)
            except gemma.GemmaError:
                log.exception("merge failed")
    applied = 0
    for field, value in changes.items():
        try:
            db.update_field(rec.id, field, value, reason=f"farmer edit: {words}", by="farmer",
                            reason_lang=rec.lang)
            applied += 1
        except ValueError as e:
            log.warning("edit of %s rejected: %s", field, e)
    if not applied:
        await say(bot, message.chat.id, db.ui("not_understood", rec.lang), rec.lang)
        return          # stay in Fix.awaiting so the farmer can say it again
    await state.clear()
    if db.get_record(rec.id).status not in ("draft", "discarded"):
        if judge(rec.id) == "needs_review":
            await notify_agronomist(bot, rec.id)
    await send_card(bot, db.get_record(rec.id))


@router.message(F.text | F.voice | F.audio)
async def on_note(message: Message, bot: Bot, state: FSMContext) -> None:
    if message.text and message.text.startswith("/"):
        return
    text, hint = await message_text(message, bot)
    await handle_note(message, bot, state, text, hint)


# --- agronomist (Task 7) -------------------------------------------------------

async def notify_agronomist(bot: Bot, rec_id: int) -> None:
    chat = os.getenv("AGRONOMIST_CHAT_ID", "").strip()
    if not chat:
        return
    rec = db.get_record(rec_id)
    qty = f"{_num(rec.quantity)} {rec.unit or ''}".strip() if rec.quantity is not None else "-"
    text = (f"<b>Needs review #{rec.id}</b> ({rec.farmer_name or rec.farmer_chat_id}, {rec.lang})\n"
            f"{rec.date or '-'} · {rec.parcel_alias or '-'} · {rec.activity_key} · {rec.product or '-'} · {qty}\n"
            f"Score {rec.judge_score:.2f}: {html.escape(rec.judge_reason or '')}\n"
            f"<i>{html.escape(rec.transcript_original)}</i>")
    try:
        await bot.send_message(int(chat), text)
    except Exception:
        log.exception("agronomist notification failed")


def _display(field: str, value: str | None, lang: str) -> str:
    if value is None:
        return "—"
    if field == "activity_key":
        return db.label("activity", value, lang)
    if field == "target_pest_key":
        return db.label("pest", value, lang)
    return value


def expert_changes(seen: set[int]) -> list[tuple[int, str]]:
    """(chat_id, message) for agronomist corrections not yet in seen; adds them to seen."""
    out = []
    for rec in db.list_records():
        if rec.corrected_by != "agronomist":
            continue
        for c in db.corrections_for(rec.id):
            if c["corrected_by"] != "agronomist" or c["id"] in seen:
                continue
            seen.add(c["id"])
            field = db.ui(FIELD_LABELS[c["field"]], rec.lang) if c["field"] in FIELD_LABELS else c["field"]
            out.append((rec.farmer_chat_id, db.ui("changed_by_expert", rec.lang).format(
                field=field, before=_display(c["field"], c["before"], rec.lang),
                after=_display(c["field"], c["after"], rec.lang))))
    return out


async def poll_expert_changes(bot: Bot) -> None:
    seen: set[int] = set()
    expert_changes(seen)            # don't re-announce corrections made before this start
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            for chat_id, text in expert_changes(seen):
                await bot.send_message(chat_id, html.escape(text))
        except Exception:
            log.exception("expert change poll failed")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    bot = Bot(os.environ["TELEGRAM_TOKEN"], default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    poller = asyncio.create_task(poll_expert_changes(bot))
    try:
        await dp.start_polling(bot)
    finally:
        poller.cancel()


if __name__ == "__main__":
    asyncio.run(main())
