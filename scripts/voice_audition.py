#!/usr/bin/env python3
"""Audition Synthia's voice: one fixed line in the current Australian voice and three British ones.

Each voice first says its own name, then the line. Wav files are saved to --out and, unless
--no-play is given, played in order. Mark picks by ear and puts the winner in brain.yaml
`voice:`; no code depends on the result.

Usage:
    venv/bin/python scripts/voice_audition.py --no-play      # just write the wav files
    venv/bin/python scripts/voice_audition.py                # write and play them in order
    venv/bin/python scripts/voice_audition.py --list         # show the en-GB Chirp3-HD voices
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

LINE = (
    "Good morning, Mark. Three agents are working and one needs you: the gallery drafts "
    "are ready to merge. Everything else is quiet."
)

# (voice name, how it introduces itself)
CANDIDATES = [
    ("en-AU-Chirp3-HD-Leda", "Leda, Australian. This is the current voice."),
    ("en-GB-Chirp3-HD-Aoede", "Aoede, British."),
    ("en-GB-Chirp3-HD-Erinome", "Erinome, British."),
    ("en-GB-Chirp3-HD-Despina", "Despina, British."),
]

DEFAULT_CREDENTIALS = Path.home() / ".config" / "synthia" / "google-creds.json"


def synthesize(client: object, voice: str, text: str) -> bytes:
    """Return a complete WAV file (LINEAR16 from the API already carries a header)."""
    from google.cloud import texttospeech

    response = client.synthesize_speech(  # type: ignore[attr-defined]
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code="-".join(voice.split("-")[:2]), name=voice
        ),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.LINEAR16),
    )
    return bytes(response.audio_content)


def play(path: Path) -> None:
    player = shutil.which("aplay") or shutil.which("paplay")
    if player is None:
        sys.exit("no wav player found (install alsa-utils or pulseaudio-utils), or use --no-play")
    cmd = [player, "-q", str(path)] if player.endswith("aplay") else [player, str(path)]
    subprocess.run(cmd, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=Path("audition"), help="where to write wavs")
    parser.add_argument("--no-play", action="store_true", help="write the files, play nothing")
    parser.add_argument("--list", action="store_true", help="list en-GB Chirp3-HD voices and exit")
    parser.add_argument("--line", default=LINE, help="override the line that is spoken")
    args = parser.parse_args()

    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds and DEFAULT_CREDENTIALS.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(DEFAULT_CREDENTIALS)

    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()

    if args.list:
        for v in client.list_voices(language_code="en-GB").voices:
            if "Chirp3-HD" in v.name:
                gender = texttospeech.SsmlVoiceGender(v.ssml_gender).name
                print(f"{v.name}  {gender}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for voice, intro in CANDIDATES:
        path = args.out / f"{voice}.wav"
        path.write_bytes(synthesize(client, voice, f"{intro} {args.line}"))
        print(f"{voice}: {path}")
        if not args.no_play:
            play(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
