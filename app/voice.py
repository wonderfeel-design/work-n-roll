"""ElevenLabs speech in and out (Person 2). Public interface, called by Person 1's bot:

    transcribe(audio_path) -> {"text": str, "lang": "en"|"ru"|"ca"|"es"}
    speak(text, lang)      -> path to an .ogg (Opus) file, or None on failure

Both calls block; from aiogram use `await asyncio.to_thread(transcribe, path)`.
Every ElevenLabs call is logged to data/logs/elevenlabs.jsonl.

    python -m app.voice transcribe data/test_notes/ca.oga
"""
import datetime as dt
import json
import logging
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

from elevenlabs.client import ElevenLabs

from app import DATA_DIR, db
from app.schemas import LANGS

log = logging.getLogger(__name__)
LOG_PATH = DATA_DIR / "logs" / "elevenlabs.jsonl"
DEFAULT_LANG = "en"

# Scribe returns ISO 639-3 codes (eng, spa, cat, rus); accept ISO 639-1 as well
_LANG_CODES = {"eng": "en", "rus": "ru", "cat": "ca", "spa": "es"} | {c: c for c in LANGS}

# Keyterms: each < 50 chars, <= 5 words, none of these characters; > 100 terms bills at least 20 s
_KEYTERM_LIMIT = 100
_KEYTERM_BAD_CHARS = set("<>{}[]\\")


class VoiceError(RuntimeError):
    """ElevenLabs call failed; the message says why. Already logged."""


@lru_cache(maxsize=1)
def _client() -> ElevenLabs:
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is not set (see .env.example)")
    return ElevenLabs(api_key=key)


def _log_call(endpoint: str, ok: bool, started: float, **fields) -> None:
    entry = {"ts": dt.datetime.now(db.TZ).isoformat(timespec="seconds"), "endpoint": endpoint, "ok": ok,
             "ms": round((time.monotonic() - started) * 1000), **fields}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("could not write %s", LOG_PATH)


def normalize_lang(code: str | None) -> str:
    """Scribe language code -> en | ru | ca | es. Anything else -> en."""
    return _LANG_CODES.get((code or "").strip().lower(), DEFAULT_LANG)


def _keyterm_ok(term: str) -> bool:
    return 0 < len(term) < 50 and len(term.split()) <= 5 and not (_KEYTERM_BAD_CHARS & set(term))


def keyterms() -> list[str]:
    """Farm words that bias Scribe: parcel names as the farmer says them, then crop and pest names."""
    try:
        terms = [n for p in db.get_parcels() for n in p["spoken_names"]]
        terms += [v[lang] for v in db.get_vocabulary() if v["type"] in ("crop", "pest")
                  for lang in LANGS if v.get(lang)]
    except Exception:  # no database yet: transcribe without bias
        log.warning("keyterms unavailable, transcribing without them", exc_info=True)
        return []
    seen, out = set(), []
    for t in (t.strip() for t in terms):
        if _keyterm_ok(t) and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:_KEYTERM_LIMIT]


def transcribe(audio_path: str) -> dict:
    """Speech to text with language detection. Telegram .oga voice notes are sent as is.

    Raises VoiceError if the file is missing or ElevenLabs fails.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise VoiceError(f"audio file not found: {path}")
    model = os.getenv("ELEVENLABS_STT_MODEL") or "scribe_v2"
    terms = keyterms()
    started = time.monotonic()
    try:
        with path.open("rb") as f:
            r = _client().speech_to_text.convert(
                model_id=model, file=(path.name, f, "audio/ogg"), tag_audio_events=False,
                keyterms=terms or None,
            )
    except Exception as e:
        _log_call("speech_to_text", False, started, model=model, file=path.name, error=str(e)[:300])
        raise VoiceError(f"Scribe failed: {e}") from e

    text = (r.text or "").strip()
    lang = normalize_lang(r.language_code)
    words = [w for w in (r.words or []) if getattr(w, "end", None) is not None]
    _log_call("speech_to_text", True, started, model=model, file=path.name, lang=lang,
              lang_raw=r.language_code, lang_prob=r.language_probability,
              seconds=round(words[-1].end, 2) if words else None, chars=len(text), keyterms=len(terms))
    return {"text": text, "lang": lang}


def speak(text: str, lang: str) -> str | None:
    """TODO(P2 Task 2): ElevenLabs TTS -> ffmpeg -> OGG/Opus. Until then the bot sends text only."""
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "transcribe" and args:
        print(json.dumps(transcribe(args[0]), ensure_ascii=False))
    elif cmd == "keyterms":
        print(json.dumps(keyterms(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
