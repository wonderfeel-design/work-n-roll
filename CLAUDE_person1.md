# CLAUDE.md — WORK_N_ROLL · Person 1 (Telegram + Gemma)

You are helping **Person 1** build their half of a 3-hour hackathon project. Read this whole file before writing code. Work **step by step**: finish one task, run its check, commit, then move on. Stop and ask when something here is ambiguous instead of guessing.

---

## 0. For the human (setup)

```bash
git clone <repo-url> work-n-roll && cd work-n-roll
git checkout -b p1-telegram-gemma
cp .env.example .env        # fill in keys
claude                      # start Claude Code in the repo root
```

First prompt to Claude Code: **"Read CLAUDE.md and start with Task 0."**

---

## 1. Project in one paragraph

**SA.TECH Field Voice.** A farmer sends a Telegram voice note (English, Russian, Catalan or Spanish). It is transcribed, Gemma 4 extracts a structured field record (CUE-style: treatments, fertilisation, irrigation, harvest, labour), a validator scores it, and the bot shows a confirmation card **in the farmer's language**. The record is stored with declaration fields in **Catalan + English** and the original transcript kept unchanged. Corrections become few-shot examples so extraction improves. Person 2 builds the voice I/O (ElevenLabs), the web table (agronomist console) and the Excel export.

Hackathon tracks: Best Open-Source AI Project, Best Use of Gemma 4, Best Use of ElevenLabs, A Judge That Learns from an Expert. Repo must stay public under Apache 2.0.

---

## 2. Who owns what

| | Person 1 (**you**) | Person 2 |
|---|---|---|
| Files you may edit | `app/bot.py`, `app/gemma.py`, `app/validator.py`, `app/prompts/*`, `tests/test_p1_*.py` | `app/voice.py`, `app/web.py`, `web/*`, `app/export.py` |
| Shared contract | `app/schemas.py`, `app/db.py`, `app/seed.py` — **create in Task 0, then change only after telling Person 2** | same |

**Rules**
- Never edit Person 2's files. If you need something from them, use the stub in Section 4 and leave a `# TODO(P2)` note.
- Any change to `schemas.py` or `db.py` after Task 0 → stop and tell the human, because Person 2 depends on it.
- Small commits, one per task: `p1: <task>`.

---

## 3. Stack (fixed — do not swap)

| Thing | Choice |
|---|---|
| Python | 3.12 |
| Telegram | `aiogram` 3, long polling (no webhook, no public URL) |
| LLM | Gemma 4 via the Gemini API, `google-genai` SDK. Model `gemma-4-26b-a4b-it`; fallback `gemma-4-31b-it` |
| Structured output | Pydantic models passed as `response_schema` with `response_mime_type="application/json"` |
| Storage | **SQLite** file `data/fieldvoice.db` (shared with Person 2's web process) |
| Speech-to-text / TTS | Person 2's `app/voice.py` (ElevenLabs Scribe + TTS). **Do not call ElevenLabs yourself.** |
| Audio | ffmpeg is installed; Person 2 handles conversions |

The Gemini API serves Gemma 4 as text + image only (no audio), which is why speech goes through Scribe.

Env vars (`.env`):
```
TELEGRAM_TOKEN=
GEMINI_API_KEY=
GEMMA_MODEL=gemma-4-26b-a4b-it
ELEVENLABS_API_KEY=        # used by Person 2 only
DB_PATH=data/fieldvoice.db
AGRONOMIST_CHAT_ID=        # optional, for review notifications
```

---

## 4. The contract (Task 0 creates this — keep it stable)

> **Task 0 is done on `main`.** Pull it; don't recreate these files. `app/schemas.py`, `app/db.py` and `app/seed.py` are the source of truth, and `tests/test_shared_db.py` checks them. Differences from the text below:
> - Optional fields default to `None` (`missing_fields=[]`, `confidence=0.0`), so a `Record` can be built without every field. The JSON Gemma returns is unchanged.
> - **Strict correction rules:** every change to a stored record goes through `update_field` (field in `schemas.EDITABLE_FIELDS`, `by` is `farmer` or `agronomist`, non-empty reason, a real change). `corrections.record_id` is a foreign key to `field_log.id`. Corrections are append-only and records are never deleted (discard them). `insert_record` only takes new drafts (`id=None`, `status="draft"`).
> - `update_status` follows `schemas.STATUS_TRANSITIONS` and raises `ValueError` otherwise. `corrected` needs an agronomist correction first.
> - **No sample data is imported.** `seed.py` loads only `Parcels_DUN`, `Vocabulary` and `UI_Strings`; the workbook's `Field_Log` and `Corrections` rows are format examples. There is no `--with-sample-log`.
> - Extra helpers: `get_farmer`, `set_farmer_name`, `label(type, key, lang)` (vocabulary label), `corrections_for(record_id)`, `set_fewshot`. `update_field` takes an optional `reason_lang`. `recent_corrections` rows include the record's `transcript_original` and `lang`.
> - Timezone for resolving "ahir" / "ayer" / "вчера": `Europe/Madrid` (`TZ_NAME` in `.env`).
> - **Storage moved to PostgreSQL** (`app/db.py`, same functions and rules). It runs in Person 2's Docker
>   (`postgres` service, port 5432). Set `DATABASE_URL=postgresql://fieldvoice:<password>@<Person 2's Wi-Fi IP>:5432/fieldvoice`
>   in `.env` (password from Person 2, privately). Tests get a throwaway schema each (`tests/conftest.py`). Mentions of
>   SQLite / `DB_PATH` below are outdated.

### 4.1 `app/schemas.py`
```python
from pydantic import BaseModel
from typing import Literal, Optional

Lang = Literal["en", "ru", "ca", "es"]
Activity = Literal["treatment", "fertilization", "irrigation", "harvest", "labour", "sowing", "other"]
Status = Literal["draft", "farmer_confirmed", "auto_approved", "needs_review",
                 "validated", "corrected", "discarded"]

class Extracted(BaseModel):              # what Gemma returns, one per activity
    lang: Lang
    date: Optional[str]                  # ISO yyyy-mm-dd, resolved ("ayer" -> real date)
    date_spoken: Optional[str]
    parcel_spoken: Optional[str]
    parcel_alias: Optional[str]          # P1..P5 or None
    crop_spoken: Optional[str]
    activity_key: Activity
    product: Optional[str]               # commercial name, never translated
    target_pest_key: Optional[str]       # vocabulary key or "unknown"
    quantity: Optional[float]
    unit: Optional[str]                  # kg, L, t, m3, ...
    area_ha: Optional[float]
    notes_ca: Optional[str]
    notes_en: Optional[str]
    missing_fields: list[str]
    confidence: float

class ExtractionResult(BaseModel):
    records: list[Extracted]
    is_farm_activity: bool

class Record(Extracted):                 # what is stored
    id: Optional[int] = None
    farmer_chat_id: int
    farmer_name: Optional[str] = None
    transcript_original: str
    status: Status = "draft"
    judge_score: Optional[float] = None
    judge_reason: Optional[str] = None
    confirmed_by: Optional[str] = None
    corrected_by: Optional[str] = None
    created_at: Optional[str] = None
```

### 4.2 `app/db.py` (SQLite, stdlib `sqlite3`, WAL mode so both processes can read/write)
Tables: `parcels`, `field_log`, `corrections`, `vocabulary`, `ui_strings`, `farmers` (`chat_id`, `name`, `last_lang`).

Functions:
```python
init_db() -> None
insert_record(rec: Record) -> int
get_record(id: int) -> Record
update_status(id: int, status: str, by: str | None = None) -> None
update_field(id: int, field: str, value, reason: str, by: str) -> None   # also inserts into corrections
list_records(limit: int = 200) -> list[Record]
recent_corrections(n: int = 5) -> list[dict]
get_parcels() -> list[dict]           # alias, spoken_names, crop_key, area_ha, sigpac_ref
get_vocabulary() -> list[dict]        # key, type, en, ca, es, ru
ui(key: str, lang: str) -> str        # UI string, falls back to "en"
set_farmer_lang(chat_id: int, lang: str) -> None
get_farmer_lang(chat_id: int) -> str | None
```

### 4.3 `app/seed.py`
Loads `data/satech_dun_field_log_sample.xlsx` (tabs `Parcels_DUN`, `Vocabulary`, `UI_Strings`, `Corrections`) into SQLite. Idempotent. **Do not** seed sample `Field_Log` rows unless `--with-sample-log` is passed (Person 2 uses that flag to build the web before real data exists).

### 4.4 Stub for Person 2's module (only if `app/voice.py` doesn't exist yet)
Create `app/voice_stub.py` (yours), and import with a fallback:
```python
try:
    from app.voice import transcribe, speak
except ImportError:
    from app.voice_stub import transcribe, speak   # TODO(P2): remove when voice.py lands
```
The stub's `transcribe()` returns `{"text": <contents of a .txt next to the audio, or "">, "lang": "en"}`, and `speak()` returns `None` (the bot then sends text only).

---

## 5. Tasks (in order)

Each task has a **Done when** check. Don't start the next task until it passes.

### Task 0 — Contract + skeleton (together with Person 2, 20 min)
- Create `app/schemas.py`, `app/db.py`, `app/seed.py` exactly as in Section 4.
- `requirements.txt` (one shared file, both halves): `aiogram>=3`, `google-genai`, `pydantic>=2`, `python-dotenv`, `openpyxl`, `pytest`, `fastapi`, `uvicorn[standard]`, `elevenlabs`.
- `.env.example`, `.gitignore` (`.env`, `data/*.db`, `data/audio/`, `data/tts/`).
- **Done when:** `python -m app.seed && python -c "from app import db; print(len(db.get_parcels()))"` prints `5`.

### Task 1 — Bot skeleton (aiogram 3)
- `app/bot.py`: `/start` (asks the farmer's name once, stores in `farmers`), handlers for **voice** and **text** messages.
- Voice: download to `data/audio/<chat_id>_<message_id>.oga`, call `transcribe()`.
- Text: treat text as the transcript; detect `lang` via Gemma in Task 2.
- Show a "processing" chat action while working.
- **Done when:** sending a text message makes the bot echo `"[lang] transcript"`.

### Task 2 — Gemma extractor (`app/gemma.py`)
- `extract(text: str, lang_hint: str | None, chat_id: int) -> ExtractionResult`.
- Build the prompt from `app/prompts/extract.md` + live data:
  - today's date (for "yesterday" / "ahir" / "вчера"),
  - parcels with `spoken_names` (to map speech → `parcel_alias`),
  - allowed vocabulary keys (activities, crops, pests) — **output keys only, never translations**,
  - last 5 corrections as few-shot examples.
- Call `gemma-4-26b-a4b-it` with `response_schema=ExtractionResult`. On failure or invalid JSON: retry once, then try `gemma-4-31b-it`.
- Rules for the prompt:
  - one voice note can contain several activities → several records,
  - `lang` = language the farmer spoke,
  - product names, numbers and units stay as spoken (normalise units: litros/литров → `L`),
  - unknown pest → `target_pest_key="unknown"` and put the farmer's phrase in notes,
  - `notes_ca` and `notes_en` = short translations of any free text,
  - list required-but-missing fields in `missing_fields` (required: `parcel_alias`, `activity_key`, `date`; plus `product` and `quantity` when activity is `treatment` or `fertilization`).
- **Done when:** `tests/test_p1_extract.py` passes on these 4 inputs (from the sample sheet):
  - CA: "Ahir vaig tirar coure a la parcel·la 3, quatre quilos per les dues hectàrees." → P3, treatment, 4 kg, lang ca
  - ES: "Catorce kilos de cobre en los almendros, toda la parcela." → P5, treatment, 14 kg, lang es
  - EN: "Watered the Gala block today, about 120 cubic metres." → P2, irrigation, 120 m3, lang en
  - RU: "Сегодня внёс сто пятьдесят килограммов NPK пятнадцать-пятнадцать-пятнадцать под яблони на втором участке." → P2, fertilization, 150 kg, lang ru

### Task 3 — Validator / judge (`app/validator.py`)
- `validate(rec: Record) -> tuple[float, str]` → `judge_score` (0–1) and a one-line `judge_reason` in English.
- Start at 1.0 and subtract:
  - −0.4 if `dose_per_ha` (= quantity / parcel area) is outside the range in `DOSE_RANGES` (a dict in this file; **values are demo placeholders, not agronomic advice — mark them so in a comment**),
  - −0.3 if `crop_spoken` doesn't match the parcel's declared crop (compare via vocabulary keys),
  - −0.3 if the date is in the future,
  - −0.2 if any `*_key` is `unknown`,
  - −0.1 per item in `missing_fields`.
- Threshold: `>= 0.80` → `auto_approved`, else `needs_review`. Put `THRESHOLD = 0.80` at the top (it's a guess to tune).
- **Done when:** R0004-style input (40 kg copper on P5) scores < 0.8 and R0001-style input scores ≥ 0.8.

### Task 4 — Missing fields → follow-up question
- If `missing_fields` isn't empty: store the partial record as `draft`, ask **one** question in the farmer's language using `db.ui("ask_parcel" | "ask_quantity", lang)`; send voice via `speak()` if available, plus text.
- The farmer's answer (voice or text) is merged into the draft by calling Gemma with the draft + answer. Max 2 rounds; after that, save with what you have.
- For a missing parcel, also show inline buttons with the farmer's parcels.
- **Done when:** "Sprayed copper today, 40 litres" → bot asks which parcel → "parcel 3" → complete card.

### Task 5 — Confirmation card
- Card text in the farmer's `lang`, labels from `ui_strings`. Show **resolved** values (real date, normalised unit, parcel alias + SIGPAC ref, crop name in the farmer's language from vocabulary, dose per ha).
- Inline buttons from `ui_strings`: `btn_ok`, `btn_edit`, `btn_discard`. Callback data: `ok:<id>`, `edit:<id>`, `del:<id>`.
- Also send the short summary as voice via `speak(text, lang)` (skip if it returns `None`).
- On ✅: `update_status(id, "farmer_confirmed", "farmer")` → run `validate()` → store score → set `auto_approved` / `needs_review` → reply `ui("saved", lang)`.
- On ❌: status `discarded`.
- Several records in one note → one card each.
- **Done when:** a voice/text note creates a row visible via `db.list_records()` with the right status.

### Task 6 — Edit flow ("just say it")
- On ✏️: use aiogram FSM state `awaiting_fix:<id>`; prompt the farmer to say or type the correction.
- Send the current record + the correction to Gemma → get the changed fields → for each changed field call `update_field(id, field, value, reason="farmer edit: <their words>", by="farmer")` → show the new card.
- **Done when:** "no, it was 14 not 40" changes quantity, creates a `corrections` row, and shows a new card.

### Task 7 — Agronomist notification (if time)
- If `AGRONOMIST_CHAT_ID` is set and a record becomes `needs_review`, send that chat a short English card with `judge_reason`. The actual correction happens on Person 2's web console.
- When a record's `corrected_by == "agronomist"` (poll every 10 s), notify the farmer with `ui("changed_by_expert", lang)`.

### Cut order if behind
Task 7 → Task 6 → Task 4. **Never cut:** Tasks 0, 1, 2, 3, 5.

---

## 6. Checkpoint at 1:30 (hard stop)

Voice note → transcript (real or stub) → card → ✅ → row in SQLite → visible on Person 2's web page. If this doesn't work at 1:30, stop adding features and fix it together.

---

## 7. Conventions

- Keep functions small and typed; Pydantic for anything crossing a boundary.
- All user-facing strings come from `ui_strings` — no hardcoded farmer-facing text in Python.
- Log every Gemma request/response to `data/logs/gemma.jsonl` (helps debugging and makes a good demo slide).
- Don't store API keys anywhere but `.env`.
- Never invent vocabulary translations in code; add missing terms to the `Vocabulary` tab and re-seed.
- Tests: `pytest -q tests/test_p1_*.py`. Gemma tests may be slow; mark them `@pytest.mark.gemma`.
- Commit after each task: `git add -A && git commit -m "p1: task N <short title>"`; push the branch `p1-telegram-gemma`. Open a PR to `main` at the checkpoint and at the end.

---

## 8. Known uncertainties (verify, don't assume)

- Exact `google-genai` call shape for Gemma structured output — check the current docs if the first call fails.
- `DOSE_RANGES` and the 0.80 threshold are demo placeholders.
- Catalan/Russian UI strings and vocabulary are drafts from the sample sheet.
- Minimum official CUE fields for phytosanitary treatments are assumed, not verified.

## 9. References
- Project README (architecture, user flow, data model): `README.md`
- Sample data: `data/satech_dun_field_log_sample.xlsx`
- Gemma 4 on the Gemini API: https://www.philschmid.de/gemma-4-gemini-api
- aiogram 3 docs: https://docs.aiogram.dev/
