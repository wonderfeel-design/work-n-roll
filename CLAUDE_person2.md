# CLAUDE.md — WORK_N_ROLL · Person 2 (Voice + Web + Output)

You are helping **Person 2** build their half of a 3-hour hackathon project. Read this whole file before writing code. Work **step by step**: finish one task, run its check, commit, then move on. Stop and ask when something here is ambiguous instead of guessing.

---

## 0. For the human (setup)

```bash
git clone <repo-url> work-n-roll && cd work-n-roll
git checkout -b p2-voice-web
# put this file in the repo root as CLAUDE.md (on this branch only)
cp .env.example .env        # fill in keys
claude                      # start Claude Code in the repo root
```

First prompt to Claude Code: **"Read CLAUDE.md and start with Task 0."**

---

## 1. Project in one paragraph

**SA.TECH Field Voice.** A farmer sends a Telegram voice note (English, Russian, Catalan or Spanish). It is transcribed, Gemma 4 extracts a structured field record (CUE-style: treatments, fertilisation, irrigation, harvest, labour), a validator scores it, and the bot shows a confirmation card **in the farmer's language**. The record is stored with declaration fields in **Catalan + English** and the original transcript kept unchanged. Corrections become few-shot examples so extraction improves. **Person 1** builds the Telegram bot and the Gemma extraction/validation. **You** build the voice I/O (ElevenLabs), the web table (agronomist console) and the Excel export.

Hackathon tracks: Best Open-Source AI Project, Best Use of Gemma 4, **Best Use of ElevenLabs** (mostly yours), **A Judge That Learns from an Expert** (the web console is where the expert corrects). Repo must stay public under Apache 2.0.

---

## 2. Who owns what

| | Person 1 | Person 2 (**you**) |
|---|---|---|
| Files | `app/bot.py`, `app/gemma.py`, `app/validator.py`, `app/prompts/*`, `app/voice_stub.py` | `app/voice.py`, `app/web.py`, `app/export.py`, `web/*`, `tests/test_p2_*.py` |
| Shared contract | `app/schemas.py`, `app/db.py`, `app/seed.py` — **created together in Task 0, then changed only after telling Person 1** | same |

**Rules**
- Never edit Person 1's files.
- Any change to `schemas.py` or `db.py` after Task 0 → stop and tell the human, because Person 1 depends on it.
- Small commits, one per task: `p2: <task>`.

---

## 3. Stack (fixed — do not swap)

| Thing | Choice |
|---|---|
| Python | 3.12 |
| Speech-to-text | ElevenLabs **Scribe** (`elevenlabs` Python SDK) — returns transcript + detected language |
| Text-to-speech | ElevenLabs multilingual TTS → **ffmpeg** → OGG/Opus (so Telegram shows a voice bubble) |
| Web backend | **FastAPI** + uvicorn, port 8000 |
| Web frontend | **One plain HTML file** (`web/index.html`) + vanilla JS `fetch`. No React, no build step |
| Live updates | **Polling every 2 s** (no SSE, no websockets) |
| Storage | **SQLite** `data/fieldvoice.db`, via the shared `app/db.py` only — never open the DB directly |
| Excel | `openpyxl` |

Env vars (`.env`):
```
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=        # one multilingual voice for all 4 languages
ELEVENLABS_TTS_MODEL=eleven_multilingual_v2
ELEVENLABS_STT_MODEL=       # Scribe model id — check current docs
DB_PATH=data/fieldvoice.db
WEB_PORT=8000
TELEGRAM_TOKEN=             # Person 1 only
GEMINI_API_KEY=             # Person 1 only
```

---

## 4. The contract (Task 0 creates this — keep it stable)

> **Task 0 is done on `main`.** `app/schemas.py`, `app/db.py` and `app/seed.py` are the source of truth, and `tests/test_shared_db.py` checks them. Differences from the text below:
> - Optional fields default to `None` (`missing_fields=[]`, `confidence=0.0`).
> - **Strict correction rules:** every change to a stored record goes through `update_field` (field in `schemas.EDITABLE_FIELDS`, `by` is `farmer` or `agronomist`, non-empty reason, a real change). `corrections.record_id` is a foreign key to `field_log.id`. Corrections are append-only and records are never deleted (discard them).
> - `update_status` follows `schemas.STATUS_TRANSITIONS` and raises `ValueError` otherwise. `corrected` needs an agronomist correction first, so PATCH calls `update_field` before `update_status`.
> - **No sample data is imported.** `seed.py` loads only `Parcels_DUN`, `Vocabulary` and `UI_Strings`. There is no `--with-sample-log`: web tests create their own records through `db.insert_record`.
> - Extra helpers: `get_farmer`, `set_farmer_name`, `label(type, key, lang)` (vocabulary label), `corrections_for(record_id)`, `set_fewshot`.
> - The web console keeps a login (`WEB_USER` / `WEB_PASSWORD`, default `admin` / `admin`), by the human's decision.
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
    date: Optional[str]                  # ISO yyyy-mm-dd
    date_spoken: Optional[str]
    parcel_spoken: Optional[str]
    parcel_alias: Optional[str]          # P1..P5 or None
    crop_spoken: Optional[str]
    activity_key: Activity
    product: Optional[str]               # commercial name, never translated
    target_pest_key: Optional[str]       # vocabulary key or "unknown"
    quantity: Optional[float]
    unit: Optional[str]
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

### 4.2 `app/db.py` (SQLite, stdlib `sqlite3`, WAL mode so the bot and web processes can share it)
Tables: `parcels`, `field_log`, `corrections`, `vocabulary`, `ui_strings`, `farmers` (`chat_id`, `name`, `last_lang`).

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
Loads `data/satech_dun_field_log_sample.xlsx` (tabs `Parcels_DUN`, `Vocabulary`, `UI_Strings`, `Corrections`) into SQLite. Idempotent. With `--with-sample-log` it also loads the sample `Field_Log` rows — **you use this flag** to build the web before Person 1's bot writes real rows.

### 4.4 Your public interface (Person 1 calls this — signatures must not change)
```python
# app/voice.py
def transcribe(audio_path: str) -> dict:     # {"text": str, "lang": "en"|"ru"|"ca"|"es"}
def speak(text: str, lang: str) -> str | None:   # path to .ogg (Opus), or None on failure
```
Until `voice.py` exists, Person 1 uses a stub with the same signatures. **Your first deliverable is replacing that stub — hand off by 0:50.**

---

## 5. Tasks (in order)

Each task has a **Done when** check. Don't start the next task until it passes.

### Task 0 — Contract + skeleton (together with Person 1, 20 min)
- Create `app/schemas.py`, `app/db.py`, `app/seed.py` exactly as in Section 4.
- `requirements.txt` (one shared file, both halves): `aiogram>=3`, `google-genai`, `pydantic>=2`, `python-dotenv`, `openpyxl`, `pytest`, `fastapi`, `uvicorn[standard]`, `elevenlabs`.
- `.env.example`, `.gitignore` (`.env`, `data/*.db`, `data/audio/`, `data/tts/`).
- **Done when:** `python -m app.seed --with-sample-log && python -c "from app import db; print(len(db.get_parcels()), len(db.list_records()))"` prints `5` and the sample row count.

### Task 1 — `transcribe()` with Scribe (`app/voice.py`)
- Send the audio file to ElevenLabs Scribe; return the transcript text and the detected language.
- Normalise the language code to `en | ru | ca | es`. Scribe may return 3-letter codes (e.g. `eng`, `rus`, `cat`, `spa`) — handle both 2- and 3-letter forms. Anything else → `"en"`.
- If the SDK supports keyterm prompting, pass agricultural terms from `db.get_vocabulary()` (product words, crops, "parcel·la", "fitosanitari"). If not, skip — don't block on it.
- Telegram voice files are `.oga` (Opus); convert with ffmpeg to wav/mp3 first **only if** Scribe rejects `.oga`.
- **Done when:** `tests/test_p2_voice.py` transcribes 4 short test recordings in `data/test_notes/` (one per language) and the detected `lang` is right for each.

### Task 2 — `speak()` with TTS (`app/voice.py`)
- Generate speech with `ELEVENLABS_TTS_MODEL` and `ELEVENLABS_VOICE_ID`, save to `data/tts/<hash>.mp3`.
- Convert with ffmpeg to OGG/Opus: `ffmpeg -y -i in.mp3 -c:a libopus -b:a 48k out.ogg`.
- Cache by hash of `(text, lang)` so repeated phrases ("Saved. Thank you!") don't cost credits.
- On any error return `None` (the bot then sends text only) and log the error.
- **Test Catalan first.** If Catalan output sounds wrong, fall back to Spanish for `lang == "ca"` and note it in the README.
- **Done when:** `speak()` produces a playable `.ogg` for one sentence in each of EN/RU/CA/ES.
- **Hand-off (target 0:50):** commit, push, tell the human "voice.py ready" so Person 1 can merge it and drop the stub.

### Task 3 — Web API (`app/web.py`)
FastAPI app, run with `uvicorn app.web:app --port 8000`.

| Method | Path | Does |
|---|---|---|
| GET | `/` | serves `web/index.html` |
| GET | `/api/records` | `db.list_records()` + joined parcel `sigpac_ref` and vocabulary `_ca` / `_en` names |
| GET | `/api/records/{id}` | one record + its corrections |
| PATCH | `/api/records/{id}` | body `{field, value, reason, by}` → `db.update_field(...)` then `db.update_status(id, "corrected", by)` |
| POST | `/api/records/{id}/approve` | `db.update_status(id, "validated", "agronomist")` |
| GET | `/api/corrections` | `db.recent_corrections(50)` |
| GET | `/api/report.xlsx` | Task 5 |

- Editable fields whitelist: `date, parcel_alias, activity_key, product, target_pest_key, quantity, unit, area_ha, notes_ca, notes_en`. Reject anything else with 400.
- `reason` is **required** for edits (it's what makes the correction a useful few-shot example).
- **Done when:** `curl localhost:8000/api/records` returns the sample rows as JSON, and a PATCH creates a `corrections` row.

### Task 4 — Agronomist console (`web/index.html`)
One self-contained HTML file, no build step.
- Table of records, newest first; refresh every 2 s with `fetch('/api/records')`. Highlight rows that are new since the last refresh.
- Columns: date, farmer, lang, parcel (alias + SIGPAC ref), crop (ca / en), activity (ca / en), product, quantity + unit, dose/ha, status, judge score, judge reason, original transcript.
- Language toggle for the table labels: **CA / EN** (the declaration languages).
- Status colours: `needs_review` amber, `auto_approved` / `validated` green, `corrected` blue, `discarded` grey. A filter button "Needs review only".
- Row actions for `needs_review`: **Approve** and **Correct**. Correct opens a small inline form: field (dropdown from the whitelist), new value, reason (required) → PATCH.
- Corrections panel on the side: last 10 corrections with before → after + reason, labelled "What the model learns from".
- Must work on a laptop screen for the demo; phone width is a bonus.
- **Done when:** with the sample rows loaded, you can approve one row and correct another, and both changes survive a page refresh.

### ✅ Checkpoint at 1:30 (hard stop)
Voice note → Person 1's bot → card → ✅ → row in SQLite → **appears in your table within 2 s** → voice reply plays in Telegram. If this doesn't work at 1:30, stop adding features and fix it together.

### Task 5 — Excel export (`app/export.py`)
- `build_report(path: str) -> str` writes an `.xlsx` with tabs `Parcels_DUN`, `Field_Log`, `Corrections`, same column order as the sample file, with declaration fields in Catalan and English.
- Arial font, frozen header row, column widths set. No formulas needed (values come from the DB).
- Expose it at `GET /api/report.xlsx` and a "Download report" button on the web page.
- Tell Person 1 the function name so the bot can send it on `/report` (their task, if time).
- **Done when:** the downloaded file opens and shows the current DB rows.

### Task 6 — 🔊 Listen button (stretch, ~20 min)
- `GET /api/summary.ogg?lang=ca` → builds a short spoken summary of today's records ("Today: 6 records, 1 needs review…") and returns `speak()` output.
- Summary sentences must come from `ui_strings` — if keys are missing, add them to the `UI_Strings` tab of the sample xlsx and re-seed (tell Person 1).
- Button on the web page plays it.
- **Done when:** clicking the button plays a Catalan (or Spanish fallback) summary.

### Not in scope (pitch as roadmap only)
ElevenLabs Agents live voice on the web, the OpenAI-compatible LLM shim, the tunnel, auth/login, photo input.

### Cut order if behind
Task 6 → Task 5 → the CA/EN label toggle. **Never cut:** Tasks 0, 1, 2, 3, 4.

---

## 6. Conventions

- Only touch the DB through `app/db.py`.
- No farmer-facing text hardcoded in Python — use `db.ui(key, lang)`. Web labels for the agronomist may live in `index.html`, in CA and EN.
- Never translate product names, registration numbers or SIGPAC references.
- Log every ElevenLabs call (endpoint, lang, characters/seconds, ok/error) to `data/logs/elevenlabs.jsonl` — useful for debugging and a good "Best Use of ElevenLabs" demo slide.
- Keep API keys only in `.env`; never expose them to the browser.
- Tests: `pytest -q tests/test_p2_*.py`. ElevenLabs tests use real credits — mark them `@pytest.mark.elevenlabs` and keep test audio short.
- Commit after each task: `git add -A && git commit -m "p2: task N <short title>"`; push `p2-voice-web`. Open a PR to `main` after Task 2 (hand-off), at the checkpoint, and at the end.

---

## 7. Known uncertainties (verify, don't assume)

- Exact `elevenlabs` SDK method names and parameters for Scribe (model id, language code format, keyterms) and TTS (output formats) — check the current SDK docs on the first call.
- Catalan quality of ElevenLabs TTS — test first; Spanish fallback is acceptable.
- Whether Scribe accepts Telegram `.oga` directly.
- Catalan/Russian UI strings and vocabulary are drafts from the sample sheet.

## 8. References
- Project README (architecture, user flow, data model): `README.md`
- Sample data: `data/satech_dun_field_log_sample.xlsx`
- ElevenLabs docs: https://elevenlabs.io/docs
- FastAPI docs: https://fastapi.tiangolo.com/
