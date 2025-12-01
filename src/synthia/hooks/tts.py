#!/usr/bin/env python3
"""
Text-to-speech for Claude Code hooks.
Reads text from stdin or argument and speaks it.

Usage:
    echo "Hello world" | python tts.py
    python tts.py "Hello world"
    python tts.py --file response.txt
"""

import sys
import os
import argparse

# Add synthia src to path dynamically (no hardcoded paths)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYNTHIA_SRC = os.path.dirname(SCRIPT_DIR)  # Go up from hooks/ to synthia/
sys.path.insert(0, SYNTHIA_SRC)

from tts import TextToSpeech
from config import load_config, get_google_credentials_path


def speak(text: str):
    """Speak the given text."""
    if not text or not text.strip():
        return

    config = load_config()
    tts = TextToSpeech(
        get_google_credentials_path(config),
        config['tts_voice'],
        config['tts_speed']
    )

    # Clean up text for speech
    text = text.strip()

    # Truncate very long text
    if len(text) > 1000:
        text = text[:1000] + "... (truncated)"

    tts.speak(text)


def main():
    parser = argparse.ArgumentParser(description="Text-to-speech for Claude Code")
    parser.add_argument("text", nargs="?", help="Text to speak")
    parser.add_argument("--file", "-f", help="File to read text from")
    args = parser.parse_args()

    if args.file:
        with open(args.file, 'r') as f:
            text = f.read()
    elif args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("No text provided. Use: echo 'text' | python tts.py", file=sys.stderr)
        sys.exit(1)

    speak(text)


if __name__ == "__main__":
    main()
