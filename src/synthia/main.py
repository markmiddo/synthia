#!/usr/bin/env python3
"""Synthia - Voice Dictation + AI Assistant for Linux.

Usage:
    Hold Right Ctrl - Dictation mode (speech to text)
    Hold Right Alt  - Assistant mode (AI voice assistant)
    Say "Hey Linux" - Wake word (when enabled)
"""

import sys
import signal
import json
import os

from synthia.config import load_config, get_google_credentials_path, get_anthropic_api_key
from synthia.audio import AudioRecorder, list_audio_devices
from synthia.transcribe import Transcriber
from synthia.output import type_text
from synthia.tts import TextToSpeech
from synthia.assistant import Assistant
from synthia.commands import execute_actions
from synthia.indicator import TrayIndicator, Status
from synthia.sounds import SoundEffects
from synthia.notifications import notify_ready, notify_dictation, notify_assistant, notify_error
from synthia.hotkeys import create_hotkey_listener
from synthia.display import is_wayland, get_display_server


class Synthia:
    """Main Synthia application."""

    def __init__(self):
        print("🚀 Starting Synthia...")

        # Load configuration
        self.config = load_config()
        print("✅ Configuration loaded")

        # Get credentials paths
        credentials_path = get_google_credentials_path(self.config)
        anthropic_key = get_anthropic_api_key(self.config)

        # Initialize sound effects
        self.sounds = SoundEffects(enabled=self.config.get("play_sound_on_record", True))

        # System tray disabled for now - icons don't render well
        self.tray = None
        # self.tray = TrayIndicator(on_quit=self._on_quit)
        # self.tray.start()
        # print("✅ System tray indicator started")

        # Initialize audio recorder
        self.recorder = AudioRecorder(
            target_sample_rate=self.config["sample_rate"]
        )
        print("✅ Audio recorder initialized")

        # Initialize transcriber (local Whisper or Google Cloud)
        use_local_stt = self.config.get("use_local_stt", False)
        self.transcriber = Transcriber(
            credentials_path=credentials_path if not use_local_stt else None,
            language=self.config["language"],
            sample_rate=self.config["sample_rate"],
            use_local=use_local_stt,
            local_model=self.config.get("local_stt_model", "small"),
        )
        print(f"✅ Transcriber initialized ({'local Whisper' if use_local_stt else 'Google Cloud'})")

        # Initialize TTS (local Piper or Google Cloud)
        use_local_tts = self.config.get("use_local_tts", False)
        self.tts = TextToSpeech(
            credentials_path=credentials_path if not use_local_tts else None,
            voice_name=self.config["tts_voice"],
            speed=self.config["tts_speed"],
            use_local=use_local_tts,
            local_voice=self.config.get("local_tts_voice", "~/.local/share/piper-voices/en_US-amy-medium.onnx"),
        )
        print(f"✅ TTS initialized ({'local Piper' if use_local_tts else 'Google Cloud'})")

        # Initialize Assistant (local Ollama or Claude API)
        use_local_llm = self.config.get("use_local_llm", False)
        self.assistant = Assistant(
            api_key=anthropic_key if not use_local_llm else None,
            model=self.config["assistant_model"],
            memory_size=self.config["conversation_memory"],
            use_local=use_local_llm,
            local_model=self.config.get("local_llm_model", "qwen2.5:7b-instruct-q4_0"),
            ollama_url=self.config.get("ollama_url", "http://localhost:11434"),
        )
        print(f"✅ Assistant initialized ({'local Ollama' if use_local_llm else 'Claude API'})")

        # State tracking
        self.dictation_active = False
        self.assistant_active = False
        self.running = True

        # State file for GUI overlay communication
        self.state_file = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
            "synthia-state.json"
        )
        # History file for voice transcription history
        self.history_file = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
            "synthia-history.json"
        )
        self._update_state("ready")

        # Parse hotkeys from config (for X11/pynput)
        self.dictation_key = self._parse_key(self.config["dictation_key"])
        self.assistant_key = self._parse_key(self.config["assistant_key"])

        # Create hotkey listener (auto-detects Wayland vs X11)
        self.hotkey_listener = create_hotkey_listener(
            on_dictation_press=self._on_dictation_press,
            on_dictation_release=self._on_dictation_release,
            on_assistant_press=self._on_assistant_press,
            on_assistant_release=self._on_assistant_release,
            dictation_key=self.dictation_key,
            assistant_key=self.assistant_key,
        )

        print(f"\n🖥️  Display server: {get_display_server()}")
        print(f"📌 Dictation key: Right Ctrl (hold to dictate)")
        print(f"📌 Assistant key: Right Alt (hold to ask AI)")
        print("\n✨ Synthia ready!\n")

        # Show notification
        if self.config.get("show_notifications", True):
            notify_ready()

    def _parse_key(self, key_string: str):
        """Parse a key string like 'Key.ctrl_r' to a pynput Key."""
        from pynput.keyboard import Key
        if key_string.startswith("Key."):
            key_name = key_string[4:]
            return getattr(Key, key_name)
        return key_string

    def _update_state(self, status: str):
        """Update state file for GUI overlay communication."""
        try:
            state = {"status": status, "recording": status == "recording"}
            with open(self.state_file, "w") as f:
                json.dump(state, f)
        except Exception:
            pass  # Non-critical, don't crash if state file can't be written

    def _save_to_history(self, text: str, mode: str, response: str = None):
        """Save transcription to history file for GUI display."""
        try:
            from datetime import datetime
            # Load existing history
            history = []
            if os.path.exists(self.history_file):
                with open(self.history_file, "r") as f:
                    history = json.load(f)

            # Add new entry
            entry = {
                "id": len(history) + 1,
                "text": text,
                "mode": mode,  # "dictation" or "assistant"
                "timestamp": datetime.now().isoformat(),
            }
            if response:
                entry["response"] = response

            history.append(entry)

            # Keep only last 50 entries
            if len(history) > 50:
                history = history[-50:]

            # Save back
            with open(self.history_file, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save history: {e}")

    def _on_quit(self):
        """Handle quit from tray icon."""
        self.running = False

    def _on_dictation_press(self):
        """Handle dictation key press (Right Ctrl)."""
        if not self.running or self.dictation_active or self.assistant_active:
            return

        try:
            self.recorder.start_recording()
            self.dictation_active = True
            self._update_state("recording")
            if self.tray:
                self.tray.set_status(Status.RECORDING)
            self.sounds.play_start()
        except Exception as e:
            print(f"❌ Could not start recording: {e}")
            self.sounds.play_error()

    def _on_dictation_release(self):
        """Handle dictation key release (Right Ctrl)."""
        if not self.running or not self.dictation_active:
            return

        try:
            self.dictation_active = False
            self._update_state("thinking")
            self.sounds.play_stop()
            if self.tray:
                self.tray.set_status(Status.THINKING)

            audio_data = self.recorder.stop_recording()

            if audio_data:
                text = self.transcriber.transcribe(audio_data)
                if text:
                    type_text(text)
                    self._save_to_history(text, "dictation")
                    if self.config.get("show_notifications", True):
                        notify_dictation(text)

            self._update_state("ready")
            if self.tray:
                self.tray.set_status(Status.READY)

        except Exception as e:
            print(f"❌ Error: {e}")
            self.sounds.play_error()
            if self.config.get("show_notifications", True):
                notify_error(str(e))
            if self.tray:
                self.tray.set_status(Status.READY)

    def _on_assistant_press(self):
        """Handle assistant key press (Right Alt)."""
        if not self.running or self.assistant_active or self.dictation_active:
            return

        try:
            self.recorder.start_recording()
            self.assistant_active = True
            self._update_state("recording")
            if self.tray:
                self.tray.set_status(Status.ASSISTANT)
            self.sounds.play_start()
        except Exception as e:
            print(f"❌ Could not start recording: {e}")
            self.sounds.play_error()

    def _on_assistant_release(self):
        """Handle assistant key release (Right Alt)."""
        if not self.running or not self.assistant_active:
            return

        try:
            self.assistant_active = False
            self._update_state("thinking")
            self.sounds.play_stop()
            if self.tray:
                self.tray.set_status(Status.THINKING)

            audio_data = self.recorder.stop_recording()

            if audio_data:
                # Transcribe the command
                text = self.transcriber.transcribe(audio_data)

                if text:
                    print(f"\n🎯 Command: {text}")

                    # Process with Claude
                    response = self.assistant.process(text)

                    # Speak the response
                    if response.get("speech"):
                        self.tts.speak(response["speech"])
                        self._save_to_history(text, "assistant", response["speech"])
                        if self.config.get("show_notifications", True):
                            notify_assistant(response["speech"])

                    # Execute any actions
                    print(f"🔧 Actions received: {response.get('actions')}")
                    if response.get("actions"):
                        results, command_output = execute_actions(response["actions"])
                        print(f"🔧 Action results: {results}")

                        # If a command returned output, speak it
                        if command_output:
                            self.tts.speak(command_output)

                    print()

            self._update_state("ready")
            if self.tray:
                self.tray.set_status(Status.READY)

        except Exception as e:
            print(f"❌ Error: {e}")
            self.sounds.play_error()
            if self.config.get("show_notifications", True):
                notify_error(str(e))
            if self.tray:
                self.tray.set_status(Status.READY)

    def run(self):
        """Run the main keyboard listener loop."""
        print("Use Ctrl+C to exit\n")

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print("\n👋 Interrupted, exiting...")
            self.running = False
            self.hotkey_listener.stop()

        signal.signal(signal.SIGINT, signal_handler)

        # Start the hotkey listener (auto-detects Wayland vs X11)
        self.hotkey_listener.start()
        self.hotkey_listener.join()

        # Cleanup
        if self.tray:
            self.tray.stop()
        self.sounds.cleanup()


def main():
    """Entry point."""
    # Show audio devices for debugging
    if "--list-devices" in sys.argv:
        list_audio_devices()
        return

    try:
        app = Synthia()
        app.run()
    except KeyboardInterrupt:
        print("\n👋 Interrupted, exiting...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()
