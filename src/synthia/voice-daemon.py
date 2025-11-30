#!/usr/bin/env python3
"""
Synthia Daemon for Claude Code
---------------------------------
Runs in background and listens for hotkey to capture voice input.
When you press the hotkey, it records, transcribes, and auto-types into Claude Code.

Usage:
    python voice-daemon.py

Hotkey: Right Ctrl (hold to record, release to transcribe)
    - Records your voice
    - Transcribes it
    - Auto-types into the active window (Claude Code)
    - Shows notification
"""

from pynput import keyboard
from pynput.keyboard import Key

from audio import AudioRecorder
from transcribe import Transcriber
from config import load_config, get_google_credentials_path
from sounds import SoundEffects
from notifications import notify
from output import type_text


class VoiceDaemon:
    def __init__(self):
        print("🎙️  Synthia Daemon for Claude Code")
        print("=" * 40)

        self.config = load_config()
        credentials_path = get_google_credentials_path(self.config)

        self.recorder = AudioRecorder(target_sample_rate=self.config["sample_rate"])
        self.transcriber = Transcriber(
            credentials_path=credentials_path,
            language=self.config["language"],
            sample_rate=self.config["sample_rate"],
        )
        self.sounds = SoundEffects(enabled=True)

        self.recording = False
        self.hotkey = Key.ctrl_r  # Right Ctrl to record

        print(f"\n✅ Ready!")
        print(f"📌 Hold Right Ctrl to record your voice")
        print(f"📝 Release to transcribe and auto-type into Claude Code\n")
        print("Press Ctrl+C to quit\n")

    def on_press(self, key):
        if key == self.hotkey and not self.recording:
            self.recording = True
            self.sounds.play_start()
            self.recorder.start_recording()

    def on_release(self, key):
        if key == self.hotkey and self.recording:
            self.recording = False
            self.sounds.play_stop()

            audio_data = self.recorder.stop_recording()

            if audio_data:
                text = self.transcriber.transcribe(audio_data)

                if text:
                    print(f"📝 You said: {text}")

                    if type_text(text):
                        notify("Voice Input", f"Typed: {text[:50]}...", timeout=2000)
                    else:
                        print(f"⚠️ Auto-type failed. Your text: {text}\n")
                else:
                    print("⚠️ No speech detected\n")

    def run(self):
        with keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        ) as listener:
            listener.join()


def main():
    try:
        daemon = VoiceDaemon()
        daemon.run()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()
