"""ElevenLabs speech in and out (Person 2). Public interface, called by Person 1's bot:

    transcribe(audio_path) -> {"text": str, "lang": "en"|"ru"|"ca"|"es"}
    speak(text, lang)      -> path to an .ogg (Opus) file, or None on failure

Both calls block; from aiogram use `await asyncio.to_thread(transcribe, path)`.
Every ElevenLabs call is logged to data/logs/elevenlabs.jsonl.

    python -m app.voice transcribe data/test_notes/ca.oga
    python -m app.voice speak "Desat. Gràcies!" ca
"""
import datetime as dt
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from elevenlabs.client import ElevenLabs

from app import DATA_DIR, db
from app.schemas import LANGS

log = logging.getLogger(__name__)
LOG_PATH = DATA_DIR / "logs" / "elevenlabs.jsonl"
TTS_DIR = DATA_DIR / "tts"
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


def _tts_settings(lang: str) -> tuple[str, str, str]:
    """(model, voice, language_code). v4 models are the ones with Catalan; multilingual_v2 has none."""
    lang = lang if lang in LANGS else DEFAULT_LANG
    model = os.getenv("ELEVENLABS_TTS_MODEL") or "eleven_v4_turbo"
    voice = os.getenv("ELEVENLABS_VOICE_ID") or "JBFqnCBsd6RMkjVDRZzb"
    return model, voice, lang


def tts_mp3(text: str, lang: str) -> Path | None:
    """Text to MP3 in data/tts, cached by (model, voice, lang, text). None on failure.

    The MP3 is what browsers play (web Listen button); speak() turns it into OGG/Opus for Telegram.
    """
    text = (text or "").strip()
    if not text:
        return None
    model, voice, lang = _tts_settings(lang)
    key = hashlib.sha256(json.dumps([model, voice, lang, text], ensure_ascii=False).encode()).hexdigest()[:24]
    mp3 = TTS_DIR / f"{key}.mp3"
    if mp3.exists():
        return mp3
    started = time.monotonic()
    try:
        audio = b"".join(_client().text_to_speech.convert(
            voice_id=voice, text=text, model_id=model, language_code=lang, output_format="mp3_44100_128"))
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = mp3.with_suffix(".part")
        tmp.write_bytes(audio)
        tmp.replace(mp3)  # never leave a half-written file in the cache
    except Exception as e:
        _log_call("text_to_speech", False, started, model=model, lang=lang, chars=len(text), error=str(e)[:300])
        log.error("TTS failed (%s): %s", lang, e)
        return None
    _log_call("text_to_speech", True, started, model=model, lang=lang, chars=len(text), bytes=len(audio))
    return mp3


def speak(text: str, lang: str) -> str | None:
    """Text to an OGG/Opus voice note for Telegram (send_voice). None on any failure: send text only."""
    mp3 = tts_mp3(text, lang)
    if mp3 is None:
        return None
    ogg = mp3.with_suffix(".ogg")
    if ogg.exists():
        return str(ogg)
    tmp = mp3.with_suffix(".tmp.ogg")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-c:a", "libopus", "-b:a", "48k", "-ac", "1", str(tmp)],
                       check=True, capture_output=True, timeout=60)
        tmp.replace(ogg)
    except (OSError, subprocess.SubprocessError) as e:
        stderr = getattr(e, "stderr", b"") or b""
        log.error("ffmpeg failed: %s %s", e, stderr.decode(errors="replace")[:300])
        tmp.unlink(missing_ok=True)
        return None
    return str(ogg)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "transcribe" and args:
        print(json.dumps(transcribe(args[0]), ensure_ascii=False))
    elif cmd == "speak" and args:
        print(speak(args[0], args[1] if len(args) > 1 else DEFAULT_LANG))
    elif cmd == "keyterms":
        print(json.dumps(keyterms(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
