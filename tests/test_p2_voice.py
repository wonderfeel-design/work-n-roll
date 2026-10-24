"""Task 1: transcribe() with ElevenLabs Scribe. Task 2: speak() with ElevenLabs TTS -> OGG/Opus.

Offline tests always run. Tests marked elevenlabs call the API:  pytest -q -m elevenlabs tests/test_p2_voice.py
"""
import json
import os
import re
import subprocess

import pytest

from app import DATA_DIR, db, seed, voice

NOTES = DATA_DIR / "test_notes"


@pytest.fixture(autouse=True)
def reference_data(pg_schema):
    """Parcels, vocabulary and UI strings: keyterms and the spoken sentences come from them."""
    seed.seed()


@pytest.mark.parametrize("code, lang", [
    ("eng", "en"), ("rus", "ru"), ("cat", "ca"), ("spa", "es"),
    ("en", "en"), ("CA", "ca"), ("fra", "en"), ("", "en"), (None, "en"),
])
def test_normalize_lang(code, lang):
    assert voice.normalize_lang(code) == lang


def test_keyterms_fit_scribe_limits():
    terms = voice.keyterms()
    assert "parcel·la 3" in terms and "второй участок" in terms
    assert len(terms) <= 100
    assert all(len(t) < 50 and len(t.split()) <= 5 for t in terms)


def test_missing_file_raises():
    with pytest.raises(voice.VoiceError):
        voice.transcribe("data/test_notes/nope.oga")


def _words(s: str) -> set[str]:
    return set(re.findall(r"\w+", s.lower().replace("ё", "е")))


# Sanity check only: Scribe writes numbers as digits ("сто пятьдесят" -> "150"), so spelled-out
# numbers never match. The strict assertion is the detected language.
MIN_OVERLAP = 0.5


@pytest.mark.elevenlabs
@pytest.mark.skipif(not os.getenv("ELEVENLABS_API_KEY"), reason="needs ELEVENLABS_API_KEY")
@pytest.mark.parametrize("lang", ["en", "ru", "ca", "es"])
def test_transcribe_detects_language(lang):
    audio = NOTES / f"{lang}.oga"
    if not audio.exists():
        pytest.skip("run: python -m scripts.make_test_notes")
    result = voice.transcribe(str(audio))
    assert set(result) == {"text", "lang"}
    assert result["lang"] == lang
    expected = _words((NOTES / f"{lang}.txt").read_text(encoding="utf-8"))
    overlap = len(expected & _words(result["text"])) / len(expected)
    assert overlap >= MIN_OVERLAP, f"transcript too far from the sentence: {result['text']!r}"
    last = json.loads(voice.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert last["endpoint"] == "speech_to_text" and last["ok"] and last["lang"] == lang


# --- Task 2: speak() -------------------------------------------------------------

needs_key = pytest.mark.skipif(not os.getenv("ELEVENLABS_API_KEY"), reason="needs ELEVENLABS_API_KEY")


def _probe(path: str) -> tuple[str, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name:format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout.split()
    return out[0], float(out[1])


def _log_lines() -> int:
    return len(voice.LOG_PATH.read_text(encoding="utf-8").splitlines()) if voice.LOG_PATH.exists() else 0


def test_speak_empty_text_returns_none():
    assert voice.speak("   ", "en") is None


def test_speak_returns_none_when_elevenlabs_fails(tmp_path, monkeypatch):
    class Broken:
        class text_to_speech:
            @staticmethod
            def convert(**kw):
                raise RuntimeError("401 invalid api key")
    monkeypatch.setattr(voice, "TTS_DIR", tmp_path / "tts")
    monkeypatch.setattr(voice, "LOG_PATH", tmp_path / "elevenlabs.jsonl")  # keep the real log clean
    monkeypatch.setattr(voice, "_client", lambda: Broken)
    assert voice.speak("Saved. Thank you!", "en") is None
    last = json.loads(voice.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert last["endpoint"] == "text_to_speech" and not last["ok"] and "401" in last["error"]
    assert not (tmp_path / "tts").exists()  # nothing half-written in the cache


@pytest.mark.elevenlabs
@needs_key
@pytest.mark.parametrize("lang", ["ca", "en", "ru", "es"])  # Catalan first
def test_speak_makes_playable_opus(lang):
    path = voice.speak(db.ui("saved", lang), lang)
    assert path and path.endswith(".ogg")
    codec, seconds = _probe(path)
    assert codec == "opus" and seconds > 0.5


@pytest.mark.elevenlabs
@needs_key
def test_speak_caches_repeated_phrases():
    first = voice.speak(db.ui("saved", "es"), "es")
    calls = _log_lines()
    assert voice.speak(db.ui("saved", "es"), "es") == first
    assert _log_lines() == calls  # served from data/tts, no new ElevenLabs call


@pytest.mark.elevenlabs
@needs_key
def test_catalan_voice_is_heard_as_catalan():
    """Round trip: if Scribe hears our Catalan TTS as Catalan, it doesn't sound Spanish."""
    text = db.ui("welcome", "ca")
    path = voice.speak(text, "ca")
    result = voice.transcribe(path)
    assert result["lang"] == "ca", f"Catalan TTS heard as {result['lang']}: {result['text']!r}"
    assert len(_words(text) & _words(result["text"])) / len(_words(text)) >= MIN_OVERLAP
