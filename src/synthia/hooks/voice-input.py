#!/usr/bin/env python3
"""
Voice input for Claude Code - captures speech and outputs text.
This can be used with UserPromptSubmit hook or run standalone to get voice input.

Usage:
    python voice-input.py              # Record until key release (needs wrapper)
    python voice-input.py --duration 5  # Record for 5 seconds
    python voice-input.py --push-to-talk # Hold Enter to record
"""

import argparse
import os
import sys
from typing import Optional

# Add synthia src to path dynamically (no hardcoded paths)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYNTHIA_SRC = os.path.dirname(SCRIPT_DIR)  # Go up from hooks/ to synthia/
sys.path.insert(0, SYNTHIA_SRC)

from audio import AudioRecorder
from config import get_google_credentials_path, load_config
from transcribe import Transcriber


def record_and_transcribe(duration: Optional[float] = None, push_to_talk: bool = False) -> str:
    """Record audio and return transcribed text."""
    config = load_config()
    credentials_path = get_google_credentials_path(config)

    recorder = AudioRecorder(target_sample_rate=config["sample_rate"])
    transcriber = Transcriber(
        credentials_path=credentials_path,
        language=config["language"],
        sample_rate=config["sample_rate"],
    )

    if push_to_talk:
        print("🎤 Press Enter to start recording, Enter again to stop...", file=sys.stderr)
        input()  # Wait for Enter
        recorder.start_recording()
        input()  # Wait for Enter to stop
        audio_data = recorder.stop_recording()
    elif duration:
        import time

        import numpy as np
        import sounddevice as sd

        print(f"🎤 Recording for {duration} seconds...", file=sys.stderr)
        frames = int(config["sample_rate"] * duration)

        # Record directly
        audio = sd.rec(
            frames,
            samplerate=recorder.device_sample_rate,
            channels=1,
            dtype=np.int16,
            device=recorder.device,
        )
        sd.wait()

        # Resample if needed
        if recorder.device_sample_rate != config["sample_rate"]:
            audio = recorder._resample(
                audio.flatten(), recorder.device_sample_rate, config["sample_rate"]
            )
            audio_data = audio.tobytes()
        else:
            audio_data = audio.tobytes()

        print("🔇 Recording stopped", file=sys.stderr)
    else:
        # Default: record for 3 seconds
        return record_and_transcribe(duration=3.0)

    if audio_data:
        text = transcriber.transcribe(audio_data)
        return str(text) if text else ""

    return ""


def main():
    parser = argparse.ArgumentParser(description="Voice input for Claude Code")
    parser.add_argument("--duration", "-d", type=float, help="Recording duration in seconds")
    parser.add_argument("--push-to-talk", "-p", action="store_true", help="Use push-to-talk mode")
    args = parser.parse_args()

    # Suppress synthia prints
    old_stdout = sys.stdout
    sys.stdout = sys.stderr

    text = record_and_transcribe(duration=args.duration, push_to_talk=args.push_to_talk)

    # Restore stdout and print result
    sys.stdout = old_stdout
    if text:
        print(text)


if __name__ == "__main__":
    main()
