"""Task 1: transcribe() with ElevenLabs Scribe.

Offline tests always run. Tests marked elevenlabs call the API:  pytest -q -m elevenlabs tests/test_p2_voice.py
"""
import json
import os
import re

import pytest

from app import DATA_DIR, voice

NOTES = DATA_DIR / "test_notes"


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
    return set(re.findall(r"\w+", s.lower()))


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
    assert overlap >= 0.6, f"transcript too far from the sentence: {result['text']!r}"
    last = json.loads(voice.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert last["endpoint"] == "speech_to_text" and last["ok"] and last["lang"] == lang
