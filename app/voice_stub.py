"""Stand-in for Person 2's app/voice.py (same signatures). TODO(P2): remove when voice.py lands.

transcribe() reads a .txt file next to the audio (data/audio/<chat>_<msg>.txt), so a voice note
can be "transcribed" in a demo by dropping its text there. speak() returns None: text-only replies.
"""
from pathlib import Path


def transcribe(audio_path: str) -> dict:
    txt = Path(audio_path).with_suffix(".txt")
    text = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
    return {"text": text, "lang": "en"}


def speak(text: str, lang: str) -> str | None:
    return None
