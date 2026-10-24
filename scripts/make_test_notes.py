"""Generate the Task 1 test notes with ElevenLabs TTS (uses ~450 characters of credit).

Writes data/test_notes/<lang>.oga (Opus, like a Telegram voice note) and <lang>.txt with the
sentence spoken. Replace the .oga files with real recordings when you have them.

    python -m scripts.make_test_notes
"""
import os
import subprocess
import tempfile

from app import DATA_DIR
from app.voice import _client

OUT = DATA_DIR / "test_notes"
MODEL = "eleven_v4"  # multilingual_v2 has no Catalan

# The four sentences from Person 1's Task 2
SENTENCES = {
    "ca": "Ahir vaig tirar coure a la parcel·la 3, quatre quilos per les dues hectàrees.",
    "es": "Catorce kilos de cobre en los almendros, toda la parcela.",
    "en": "Watered the Gala block today, about 120 cubic metres.",
    "ru": "Сегодня внёс сто пятьдесят килограммов NPK пятнадцать-пятнадцать-пятнадцать под яблони на втором участке.",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    for lang, text in SENTENCES.items():
        audio = b"".join(_client().text_to_speech.convert(
            voice_id=voice_id, text=text, model_id=MODEL, output_format="mp3_44100_128"))
        with tempfile.NamedTemporaryFile(suffix=".mp3") as mp3:
            mp3.write(audio)
            mp3.flush()
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3.name,
                            "-c:a", "libopus", "-b:a", "32k", "-ac", "1", str(OUT / f"{lang}.oga")], check=True)
        (OUT / f"{lang}.txt").write_text(text + "\n", encoding="utf-8")
        print(f"{lang}: {OUT / f'{lang}.oga'}")


if __name__ == "__main__":
    main()
