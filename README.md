# WORK'n'Roll Field Voice logger

**Farmers talk, the field log fills itself.** A farmer sends a Telegram voice note in English, Russian, Catalan or Spanish. ElevenLabs Scribe transcribes it, Gemma 4 turns it into a structured field record (CUE-style: treatments, fertilisation, irrigation, harvest, labour), a validator scores it, and the bot reads it back in the farmer's language for confirmation. An agronomist reviews and corrects records on a web console, and every correction becomes a few-shot example, so the extractor and the judge learn from the expert. The log exports to Excel in the same layout as the sample sheet.

Hackathon tracks: Best Open-Source AI Project · Best Use of Gemma 4 · Best Use of ElevenLabs · A Judge That Learns from an Expert.
License: Apache 2.0.

- [Architecture](#architecture)
- [User flow](#user-flow)
- [Data model](#data-model)
- [Decisions](#decisions)
- [Roadmap (full v1 architecture)](#roadmap-full-v1-architecture)
- [Running locally](#running-locally)

---

## Architecture

The MVP is built in 3 hours by two people. Two Python processes share one SQLite file.

```
                        ┌──────────────────────── Person 1 ────────────────────────┐
 Farmer ── voice/text ──▶ Telegram ──▶ app/bot.py (aiogram 3, long polling)         │
   ▲                     │               │  1. voice.transcribe()  ───────────────────┼──▶ ElevenLabs Scribe
   │                     │               │  2. gemma.extract()     ───────────────────┼──▶ Gemini API · Gemma 4
   │                     │               │  3. validator.validate()  (rules, score)   │
   │                     │               │  4. confirmation card ✅ ✏️ ❌              │
   └── card + voice ─────┤               │  5. voice.speak()       ───────────────────┼──▶ ElevenLabs TTS → ffmpeg → OGG/Opus
                         └───────────────┼───────────────────────────────────────────┘
                                         ▼
                              data/fieldvoice.db  (SQLite, WAL)
                              parcels · field_log · corrections
                              vocabulary · ui_strings · farmers
                                         ▲
                         ┌───────────────┼──────────── Person 2 ─────────────────────┐
 Agronomist ── browser ──▶ app/web.py (FastAPI :8000) ◀── web/index.html (poll 2 s)  │
   ▲                     │   approve · correct (+reason) · corrections panel        │
   └── .xlsx ────────────┤   app/export.py  (openpyxl, layout of the sample sheet)  │
                         └──────────────────────────────────────────────────────────┘
```

| Component | Owner | Files | Job |
|---|---|---|---|
| Telegram bot | Person 1 | `app/bot.py` | Receives voice and text, runs the pipeline, shows the confirmation card, handles ✅ ✏️ ❌ |
| Extractor | Person 1 | `app/gemma.py`, `app/prompts/*` | Gemma 4 → JSON records. Prompt gets today's date, parcels with spoken names, vocabulary keys and the last 5 corrections |
| Validator (judge) | Person 1 | `app/validator.py` | Rule-based score 0–1: dose range, crop vs. parcel, future date, unknown keys, missing fields. ≥ 0.80 auto-approves |
| Voice I/O | Person 2 | `app/voice.py` | `transcribe()` with Scribe (text + detected language), `speak()` with multilingual TTS → OGG/Opus |
| Agronomist console | Person 2 | `app/web.py`, `web/index.html` | Live table, approve, correct with a required reason, corrections panel |
| Excel export | Person 2 | `app/export.py` | `.xlsx` with the sample sheet's tabs and columns |
| Shared contract | both | `app/schemas.py`, `app/db.py`, `app/seed.py` | Pydantic models, SQLite access, seeding from the sample workbook. Changed only by agreement |

Per-person build instructions: [CLAUDE_person1.md](CLAUDE_person1.md), [CLAUDE_person2.md](CLAUDE_person2.md).

## User flow

**1. Log an activity.** The farmer says *"Ahir vaig tirar coure a la parcel·la 3, quatre quilos per les dues hectàrees."*
Scribe returns the transcript and `ca`. Gemma maps "parcel·la 3" to P3 and "ahir" to yesterday's date in Europe/Madrid, and returns: treatment, copper, 4 kg, 2 ha. A voice note can hold several activities, which become several records.

**2. Missing fields.** If the parcel or quantity is missing, the bot asks one follow-up question in the farmer's language (parcel buttons for a missing parcel), at most 2 rounds.

**3. Confirm.** The bot shows a card in the farmer's language (resolved date, parcel + SIGPAC ref, crop, dose per ha) and reads it out as a voice note.
- ✅ → `farmer_confirmed` → validator → `auto_approved` (score ≥ 0.80) or `needs_review`
- ✏️ → the farmer just says the fix (*"no, it was 14 not 40"*) → Gemma finds the changed field → stored as a correction
- ❌ → `discarded`

**4. Expert review.** The agronomist sees `needs_review` rows in amber on the web console, then approves (`validated`) or corrects a field with a reason (`corrected`). The correction appears in the "What the model learns from" panel and in the next extraction prompt.

**5. Report.** `/report` in Telegram or the web's download button produces the `.xlsx`.

Status flow:

```
draft → farmer_confirmed → auto_approved ─┐
                         └→ needs_review ─┴→ validated | corrected
(any) → discarded
```

## Data model

Source of truth: [app/schemas.py](app/schemas.py) and [app/db.py](app/db.py), checked by [tests/test_shared_db.py](tests/test_shared_db.py). Reference data comes from [data/satech_dun_field_log_sample.xlsx](data/satech_dun_field_log_sample.xlsx).

| Table | Holds | Seeded from |
|---|---|---|
| `parcels` | The farm's DUN parcels: alias (P1–P5), spoken names in all languages, SIGPAC ref, crop key, area | `Parcels_DUN` tab |
| `field_log` | One row per activity (`Record`): extracted fields, original transcript, status, judge score and reason | Starts empty |
| `corrections` | Every edit: record (foreign key), field, before → after, reason, who, when. The last N go into the prompts as few-shot examples | Starts empty |
| `vocabulary` | Canonical keys (activity, crop, pest, product, unit) with `en`, `ca`, `es`, `ru` labels | `Vocabulary` tab |
| `ui_strings` | Every farmer-facing sentence and button label in 4 languages | `UI_Strings` tab |
| `farmers` | Telegram chat id, name, last language | Filled by `/start` |

Rules:
- Gemma outputs **vocabulary keys**, never translations. Labels in each language come from `vocabulary`.
- Declaration fields are stored in Catalan + English (`notes_ca`, `notes_en`). The original transcript is kept unchanged.
- Product names, registration numbers and SIGPAC references are never translated.
- The workbook shows the **format**. Its Field_Log and Corrections rows are examples and are never imported.

Correction rules (enforced by `app/db.py` and the SQLite schema):
- Every change to a stored record goes through `update_field`, which writes the new value and a `corrections` row in one transaction.
- A correction needs an existing record, an editable field, `farmer` or `agronomist` as author, a non-empty reason and a real change.
- Corrections are append-only (only `used_as_fewshot` can be switched off). Records are never deleted; they are discarded.
- Status only moves along the flow above; `corrected` requires an agronomist correction; `discarded` is final.

## Decisions

Decided during design on 2026-10-24. The full v1 architecture was cut to fit 3 hours; cut items are in the [roadmap](#roadmap-full-v1-architecture).

| # | Topic | Decision | Why |
|---|---|---|---|
| 1 | LLM | `gemma-4-26b-a4b-it` on the Gemini API; `gemma-4-31b-it` as a per-call fallback | The mixture-of-experts model is fast and cheap (about 4B active parameters) and reads images. One model keeps prompts simple |
| 2 | Speech-to-text | ElevenLabs Scribe, one transcript | The Gemini API serves Gemma 4 without audio input, so Gemma can't listen to compare transcripts. Mistakes are caught by the validator's range checks and the farmer's read-back instead |
| 3 | Voice replies | ElevenLabs TTS `eleven_v4_turbo` with `language_code`, converted with ffmpeg to OGG/Opus, cached by text in `data/tts` | Telegram only shows a voice bubble for OGG/Opus; MP3 would appear as a music file. `eleven_multilingual_v2` has no Catalan; v4 has all four languages and turbo answers in ~0.4 s. Catalan TTS passes a round trip (Scribe hears it as Catalan), so no Spanish fallback is needed |
| 3a | Speech-to-text model | Scribe `scribe_v2` with ~57 keyterms (parcel names, crops, pests) | Keyterms bias recognition toward farm words; kept under 100 to avoid a 20 s minimum charge per note |
| 4 | Confirmation | The farmer confirms **every** row, then the validator scores it. ≥ 0.80 auto-approves, below goes to the agronomist | Follows the sample sheet's status flow. The read-back is the safety net for transcription errors. 0.80 is a guess to tune |
| 5 | Timezone | Europe/Madrid | Resolving "ahir" / "ayer" / "вчера" / "yesterday" to a date |
| 6 | Parcels | Seed the 5 sample parcels from `Parcels_DUN`; no adding parcels by voice | The DUN parcel list is filled once per farm. The bot needs it to map spoken names to P1–P5 |
| 7 | Users | One farmer for now | MVP scope. The `farmers` table already allows more later |
| 8 | Sample workbook | Format reference only. Seeding loads Parcels_DUN, Vocabulary and UI_Strings; Field_Log and Corrections start empty | The rows are fictional examples |
| 8a | Corrections | Strict: foreign key to the record, required reason, append-only, records never deleted | Corrections are the training signal for the judge; they must be trustworthy |
| 9 | Database | SQLite (WAL) instead of PostgreSQL + pgvector | No server to run; the bot and web processes share one file. Full-text search over notes is a later job |
| 10 | Live updates | Web polls every 2 s instead of SSE + LISTEN/NOTIFY | Looks the same in a demo, saves about an hour |
| 11 | Web frontend | One plain HTML file + `fetch` instead of React + Vite + TanStack Table | No build step |
| 12 | Web role | The web page is the agronomist console | Gives the "Judge That Learns from an Expert" track a home without extra work |
| 13 | Web login | `admin` / `admin` by default, configurable in `.env` | Change it before anything is exposed publicly |
| 14 | Telegram | aiogram 3, long polling | Works locally without a webhook or public URL |
| 15 | Excel | Export only, never imported back; same tabs and column order as the sample | The database is the system of record |
| 16 | Work split | Person 1: Telegram + Gemma. Person 2: voice + web + export (all ElevenLabs calls) | Equal load; one person owns all ElevenLabs keys and quirks |
| 17 | Python | 3.12 | Fixed stack in the CLAUDE files |
| 18 | Web voice assistant | Turn-based: tap the orb, speak, a pause ends the question; Scribe → LLM → ElevenLabs TTS in a voice picked from the account; subtitles under the orb; it listens again for follow-ups | Runs locally with no public URL (no ElevenLabs Agents tunnel). About 3 s from the end of the question to the start of the answer |
| 19 | Assistant data | The server computes totals, counts and average dose per hectare in Python (by product, parcel, month) and gives them to the LLM with the records; the LLM only phrases the answer | Exact arithmetic, and nothing the LLM writes can reach the database. "Bought" is answered as "used": the log records applications, not purchases |
| 20 | Assistant model | `gemini-3.5-flash` (`ASSISTANT_MODEL`), Gemma 4 as fallback; the bot's extraction stays on Gemma | Gemma 4 on the Gemini API always thinks for 12–18 s before answering and that can't be switched off; Flash answers the same questions correctly in ~1.5 s |

## Roadmap (full v1 architecture)

Designed, not in the 3-hour MVP:

- **Live voice on the web:** ElevenLabs Agents for mic streaming and turn-taking, with a *custom LLM* pointing at our OpenAI-compatible shim (`/v1/chat/completions`), so Gemma 4 still does the reasoning. Needs a public HTTPS URL (cloudflared tunnel; accepted) and a shared secret on the shim.
- **Q&A / edit agent** in chat with tools: `query_log` (read-only SQL views under a read-only DB role with a statement timeout), `search_notes`, `update_record`, `add_record`, `export_report`.
- **Photo input:** bills and product labels read by Gemma vision; `gemma-4-31b-it` for hard photos.
- **PostgreSQL 16** with SSE live updates via LISTEN/NOTIFY, `record_history` for every edit, raw `messages` with audio and photo paths, then full-text or pgvector search.
- **React + Vite + TanStack Table** web app with editable cells.
- **Signed `/web` links** from the bot, exchanged for a cookie.
- **Several farmers**, each with their own ROPO licence and default equipment.
- `docker compose up` for postgres, api, web and tunnel.

## Running locally

With Docker (needs only Docker Desktop):

```bash
cp .env.example .env                       # fill in keys
docker compose up --build                  # seed, the console on http://localhost:8000, the bot
docker compose down                        # stop; add -v to also delete the database volume
```

One image runs every process. Keys are read from `.env` at start and never copied into the image. The database, audio and exports live in the `fieldvoice-data` volume. The console listens on `127.0.0.1` only.

Without Docker:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                       # fill in keys
.venv/bin/python -m app.seed               # parcels, vocabulary, UI strings
.venv/bin/python -m pytest -q              # contract tests
.venv/bin/python -m app.bot                # Person 1: Telegram bot
.venv/bin/uvicorn app.web:app --port 8000  # Person 2: http://localhost:8000
```

Requires ffmpeg (`brew install ffmpeg`).
