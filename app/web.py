"""Work'n'Roll · Epic Reporting: the agronomist console API (Person 2, Tasks 3-6).

    uvicorn app.web:app --port 8000      -> http://localhost:8000  (WEB_USER / WEB_PASSWORD, default admin / admin)

The bot writes to the same PostgreSQL database from its own process; the page polls /api/records every 2 s.
Everything except /api/health and the icons in /static needs the login. The console always acts as the agronomist.
"""
import base64
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ValidationError

from app import ROOT, assistant, db, export, voice
from app.schemas import LANGS, STATUS_TRANSITIONS, Record

INDEX_HTML = ROOT / "web" / "index.html"
STATIC_DIR = ROOT / "web" / "static"  # app icons: public, browsers fetch favicons without the login
REALM = "Work'n'Roll"
EXPERT = "agronomist"
# What the agronomist may correct from the console (a subset of schemas.EDITABLE_FIELDS)
WEB_EDITABLE = ("date", "parcel_alias", "activity_key", "product", "target_pest_key",
                "quantity", "unit", "area_ha", "notes_ca", "notes_en")

security = HTTPBasic(realm=REALM)


def require_login(creds: HTTPBasicCredentials = Depends(security)) -> str:
    ok_user = secrets.compare_digest(creds.username.encode(), os.getenv("WEB_USER", "admin").encode())
    ok_pass = secrets.compare_digest(creds.password.encode(), os.getenv("WEB_PASSWORD", "admin").encode())
    if not (ok_user and ok_pass):
        raise HTTPException(401, "Wrong user or password", headers={"WWW-Authenticate": f'Basic realm="{REALM}"'})
    return creds.username


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Work'n'Roll · Epic Reporting", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
api = APIRouter(prefix="/api", dependencies=[Depends(require_login)])


@app.get("/api/health", include_in_schema=False)
def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False, dependencies=[Depends(require_login)])
def index() -> FileResponse:
    if not INDEX_HTML.exists():
        raise HTTPException(404, "web/index.html is not built yet")
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-store"})


# --- read ----------------------------------------------------------------------

class _Lookups:
    """Parcels and vocabulary, loaded once per request to enrich records for the table."""

    def __init__(self) -> None:
        self.parcels = {p["alias"]: p for p in db.get_parcels()}
        self.vocab = {(v["type"], v["key"]): v for v in db.get_vocabulary()}

    def names(self, type: str, key: Optional[str]) -> dict:
        v = self.vocab.get((type, key)) or self.vocab.get(("any", key)) or {}
        return {"ca": v.get("ca") or key, "en": v.get("en") or key}

    def enrich(self, rec: Record) -> dict:
        out = rec.model_dump()
        parcel = self.parcels.get(rec.parcel_alias) or {}
        crop_key = parcel.get("crop_key")
        area = rec.area_ha or parcel.get("area_ha")
        crop, activity, pest = (self.names("crop", crop_key), self.names("activity", rec.activity_key),
                                self.names("pest", rec.target_pest_key))
        out.update(
            record_id=f"R{rec.id:04d}",
            sigpac_ref=parcel.get("sigpac_ref"),
            crop_key=crop_key,
            crop_ca=crop["ca"], crop_en=crop["en"],
            activity_ca=activity["ca"], activity_en=activity["en"],
            target_pest_ca=pest["ca"] if rec.target_pest_key else None,
            target_pest_en=pest["en"] if rec.target_pest_key else None,
            dose_per_ha=round(rec.quantity / area, 3) if rec.quantity is not None and area else None,
        )
        return out


def _get_or_404(id: int) -> Record:
    try:
        return db.get_record(id)
    except KeyError:
        raise HTTPException(404, f"No record {id}")


@api.get("/records")
def list_records(limit: int = 200) -> list[dict]:
    """Newest first, with SIGPAC ref, declared crop, CA/EN names and dose per ha."""
    lookups = _Lookups()
    return [lookups.enrich(r) for r in db.list_records(limit)]


@api.get("/records/{id}")
def get_record(id: int) -> dict:
    rec = _get_or_404(id)
    return {**_Lookups().enrich(rec), "corrections": db.corrections_for(id)}


@api.get("/corrections")
def corrections() -> list[dict]:
    return db.recent_corrections(50)


@api.get("/parcels")
def parcels() -> list[dict]:
    return db.get_parcels()


@api.get("/vocabulary")
def vocabulary() -> list[dict]:
    return db.get_vocabulary()


@api.get("/voices")
def voices() -> dict:
    """ElevenLabs voices for the assistant's picker; the configured default comes first in the UI."""
    try:
        return {"default": voice.default_voice_id(), "voices": list(voice.list_voices())}
    except Exception as e:
        raise HTTPException(503, f"ElevenLabs voices unavailable: {e}")


ASK_MAX_BYTES = 5 * 1024 * 1024  # ~ several minutes of Opus; a question is a few seconds


@api.post("/ask")
def ask(audio: Optional[UploadFile] = File(None), text: str = Form(""), lang: str = Form("en"),
        voice_id: str = Form(""), history: str = Form("[]")) -> dict:
    """Voice Q&A (Task 6): recorded question -> Scribe -> Gemma over the field log -> TTS in the chosen voice.

    `text` replaces the recording (tests, typed questions); `lang` is then the answer language.
    """
    timings, started = {}, time.monotonic()
    question = text.strip()
    if audio is not None:
        data = audio.file.read(ASK_MAX_BYTES + 1)
        if len(data) > ASK_MAX_BYTES:
            raise HTTPException(413, "Recording too long")
        suffix = Path(audio.filename or "").suffix.lower() or ".webm"
        tmp = voice.DATA_DIR / "audio" / f"web-{uuid.uuid4().hex[:12]}{suffix}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        try:
            heard = voice.transcribe(str(tmp))
        except voice.VoiceError as e:
            raise HTTPException(502, f"Speech recognition failed: {e}")
        finally:
            tmp.unlink(missing_ok=True)
        question, lang = heard["text"], heard["lang"]
        timings["stt_ms"] = round((time.monotonic() - started) * 1000)
    if not question:
        raise HTTPException(422, "No question heard")
    if lang not in LANGS:
        lang = "en"
    try:
        turns = json.loads(history or "[]")
        turns = [t for t in turns if isinstance(t, dict)] if isinstance(turns, list) else []
    except json.JSONDecodeError:
        turns = []

    t = time.monotonic()
    try:
        reply = assistant.answer(question, lang, turns)
    except assistant.AssistantError as e:
        raise HTTPException(502, f"No answer model responded: {e}")
    timings["llm_ms"] = round((time.monotonic() - t) * 1000)

    t = time.monotonic()
    known = {v["voice_id"] for v in voice.list_voices()} if voice_id else set()
    mp3 = voice.tts_mp3(reply, lang, voice_id if voice_id in known else None)
    timings["tts_ms"] = round((time.monotonic() - t) * 1000)
    timings["total_ms"] = round((time.monotonic() - started) * 1000)
    return {"question": question, "lang": lang, "answer": reply, "timings": timings,
            "audio": base64.b64encode(mp3.read_bytes()).decode() if mp3 else None}


@api.get("/report.xlsx")
def report() -> FileResponse:
    """Excel report in the sample workbook's layout (Task 5), built fresh on every request."""
    path = Path(export.build_report())
    return FileResponse(path, filename=path.name, headers={"Cache-Control": "no-store"},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --- write ---------------------------------------------------------------------

class Correction(BaseModel):
    field: str
    value: Any = None
    reason: str = ""
    by: str = EXPERT


@api.patch("/records/{id}")
def correct(id: int, body: Correction) -> dict:
    """Expert correction: one field, required reason. Logged to corrections, status becomes corrected."""
    if body.field not in WEB_EDITABLE:
        raise HTTPException(400, f"{body.field!r} cannot be edited here; allowed: {', '.join(WEB_EDITABLE)}")
    if body.by != EXPERT:
        raise HTTPException(400, "the console only records agronomist corrections")
    if not body.reason.strip():
        raise HTTPException(422, "A reason is required: it is what the model learns from")
    rec = _get_or_404(id)
    # Check the status move before writing, so a refused move never leaves a half-applied edit
    if "corrected" not in STATUS_TRANSITIONS[rec.status]:
        raise HTTPException(409, f"A {rec.status} record cannot be corrected yet")
    try:
        db.update_field(id, body.field, body.value, body.reason, EXPERT)
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, str(e))
    except db.IntegrityError as e:  # e.g. a parcel that doesn't exist; the transaction rolled back
        raise HTTPException(422, f"{body.field} = {body.value!r} is not allowed ({e})")
    db.update_status(id, "corrected", EXPERT)
    return get_record(id)


@api.post("/records/{id}/approve")
def approve(id: int) -> dict:
    rec = _get_or_404(id)
    if "validated" not in STATUS_TRANSITIONS[rec.status]:
        raise HTTPException(409, f"A {rec.status} record cannot be approved")
    db.update_status(id, "validated", EXPERT)
    return get_record(id)


app.include_router(api)
