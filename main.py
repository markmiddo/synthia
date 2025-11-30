#!/usr/bin/env python3
"""LinuxVoice - Voice Dictation + AI Assistant for Linux.

Usage:
    Hold Right Ctrl - Dictation mode (speech to text)
    Hold Right Alt  - Assistant mode (AI voice assistant)
    Say "Hey Linux" - Wake word (when enabled)
"""

import sys
import signal
from pynput import keyboard
from pynput.keyboard import Key

from config import load_config, get_google_credentials_path, get_anthropic_api_key
from audio import AudioRecorder, list_audio_devices
from transcribe import Transcriber
from output import type_text
from tts import TextToSpeech
from assistant import Assistant
from commands import execute_actions
from indicator import TrayIndicator, Status
from sounds import SoundEffects
from notifications import notify_ready, notify_dictation, notify_assistant, notify_error


class LinuxVoice:
    """Main LinuxVoice application."""

    def __init__(self):
        print("🚀 Starting LinuxVoice...")

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

        # Initialize transcriber
        self.transcriber = Transcriber(
            credentials_path=credentials_path,
            language=self.config["language"],
            sample_rate=self.config["sample_rate"],
        )
        print("✅ Transcriber initialized")

        # Initialize TTS
        self.tts = TextToSpeech(
            credentials_path=credentials_path,
            voice_name=self.config["tts_voice"],
            speed=self.config["tts_speed"],
        )
        print("✅ TTS initialized")

        # Initialize Assistant
        self.assistant = Assistant(
            api_key=anthropic_key,
            model=self.config["assistant_model"],
            memory_size=self.config["conversation_memory"],
        )
        print("✅ Assistant initialized")

        # State tracking
        self.dictation_active = False
        self.assistant_active = False
        self.running = True

        # Parse hotkeys from config
        self.dictation_key = self._parse_key(self.config["dictation_key"])
        self.assistant_key = self._parse_key(self.config["assistant_key"])

        print(f"\n📌 Dictation key: {self.config['dictation_key']} (hold to dictate)")
        print(f"📌 Assistant key: {self.config['assistant_key']} (hold to ask AI)")
        print("\n✨ LinuxVoice ready!\n")

        # Show notification
        if self.config.get("show_notifications", True):
            notify_ready()

    def _parse_key(self, key_string: str) -> Key:
        """Parse a key string like 'Key.ctrl_r' to a pynput Key."""
        if key_string.startswith("Key."):
            key_name = key_string[4:]
            return getattr(Key, key_name)
        return key_string

    def _on_quit(self):
        """Handle quit from tray icon."""
        self.running = False

    def on_press(self, key):
        """Handle key press events."""
        if not self.running:
            return False

        try:
            # Dictation mode - Right Ctrl
            if key == self.dictation_key and not self.dictation_active and not self.assistant_active:
                try:
                    self.recorder.start_recording()
                    self.dictation_active = True
                    if self.tray:
                        self.tray.set_status(Status.RECORDING)
                    self.sounds.play_start()
                except Exception as e:
                    print(f"❌ Could not start recording: {e}")
                    self.sounds.play_error()

            # Assistant mode - Right Alt
            elif key == self.assistant_key and not self.assistant_active and not self.dictation_active:
                try:
                    self.recorder.start_recording()
                    self.assistant_active = True
                    if self.tray:
                        self.tray.set_status(Status.ASSISTANT)
                    self.sounds.play_start()
                except Exception as e:
                    print(f"❌ Could not start recording: {e}")
                    self.sounds.play_error()

        except AttributeError:
            pass

    def on_release(self, key):
        """Handle key release events."""
        if not self.running:
            return False

        try:
            # Dictation mode - transcribe and type
            if key == self.dictation_key and self.dictation_active:
                self.dictation_active = False
                self.sounds.play_stop()
                if self.tray:
                    self.tray.set_status(Status.THINKING)

                audio_data = self.recorder.stop_recording()

                if audio_data:
                    text = self.transcriber.transcribe(audio_data)
                    if text:
                        type_text(text)
                        if self.config.get("show_notifications", True):
                            notify_dictation(text)

                if self.tray:
                    self.tray.set_status(Status.READY)

            # Assistant mode - transcribe, process with Claude, speak response, execute actions
            elif key == self.assistant_key and self.assistant_active:
                self.assistant_active = False
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

                if self.tray:
                    self.tray.set_status(Status.READY)

            # Escape to quit
            elif key == Key.esc:
                print("\n👋 Exiting LinuxVoice...")
                self.running = False
                return False

        except AttributeError:
            pass
        except Exception as e:
            print(f"❌ Error: {e}")
            self.sounds.play_error()
            if self.config.get("show_notifications", True):
                notify_error(str(e))
            if self.tray:
                self.tray.set_status(Status.READY)

    def run(self):
        """Run the main keyboard listener loop."""
        print("Press ESC to exit\n")

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print("\n👋 Interrupted, exiting...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)

        with keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        ) as listener:
            listener.join()

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
        app = LinuxVoice()
        app.run()
    except KeyboardInterrupt:
        print("\n👋 Interrupted, exiting...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()
