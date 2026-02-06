#!/usr/bin/env python3
"""Synthia - Voice Dictation + AI Assistant for Linux.

Usage:
    Hold Right Ctrl - Dictation mode (speech to text)
    Hold Right Alt  - Assistant mode (AI voice assistant)
    Say "Hey Linux" - Wake word (when enabled)
"""

import json
import logging
import os
import signal
import sys
import threading
import time

from synthia.assistant import Assistant
from synthia.audio import AudioRecorder, list_audio_devices
from synthia.commands import execute_actions
from synthia.config import apply_word_replacements, get_anthropic_api_key, get_google_credentials_path, load_config
from synthia.display import get_display_server, is_wayland
from synthia.hotkeys import create_hotkey_listener
from synthia.indicator import Status, TrayIndicator
from synthia.notifications import notify_assistant, notify_dictation, notify_error, notify_ready
from synthia.output import type_text
from synthia.sounds import SoundEffects
from synthia.transcribe import Transcriber
from synthia.tts import TextToSpeech
from synthia.llm_polish import TranscriptionPolisher
from synthia.clipboard_monitor import ClipboardMonitor

logger = logging.getLogger(__name__)


class Synthia:
    """Main Synthia application."""

    def __init__(self):
        logger.info("Starting Synthia...")

        # Load configuration
        self.config = load_config()
        logger.info("Configuration loaded")

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
        self.recorder = AudioRecorder(target_sample_rate=self.config["sample_rate"])
        logger.info("Audio recorder initialized")

        # Initialize transcriber (local Whisper or Google Cloud)
        use_local_stt = self.config.get("use_local_stt", False)
        self.transcriber = Transcriber(
            credentials_path=credentials_path if not use_local_stt else None,
            language=self.config["language"],
            sample_rate=self.config["sample_rate"],
            use_local=use_local_stt,
            local_model=self.config.get("local_stt_model", "small"),
        )
        logger.info(
            "Transcriber initialized (%s)", "local Whisper" if use_local_stt else "Google Cloud"
        )

        # Initialize TTS (local Piper or Google Cloud)
        use_local_tts = self.config.get("use_local_tts", False)
        self.tts = TextToSpeech(
            credentials_path=credentials_path if not use_local_tts else None,
            voice_name=self.config["tts_voice"],
            speed=self.config["tts_speed"],
            use_local=use_local_tts,
            local_voice=self.config.get(
                "local_tts_voice", "~/.local/share/piper-voices/en_US-amy-medium.onnx"
            ),
        )
        logger.info("TTS initialized (%s)", "local Piper" if use_local_tts else "Google Cloud")

        # Initialize Assistant (local Ollama or Claude API)
        use_local_llm = self.config.get("use_local_llm", False)
        dev_mode = self.config.get("memory_auto_retrieve", False)
        self.assistant = Assistant(
            api_key=anthropic_key if not use_local_llm else None,
            model=self.config["assistant_model"],
            memory_size=self.config["conversation_memory"],
            use_local=use_local_llm,
            local_model=self.config.get("local_llm_model", "qwen2.5:7b-instruct-q4_0"),
            ollama_url=self.config.get("ollama_url", "http://localhost:11434"),
            dev_mode=dev_mode,
        )
        logger.info("Assistant initialized (%s)", "local Ollama" if use_local_llm else "Claude API")
        if dev_mode:
            logger.info("Memory auto-retrieval enabled (dev mode)")

        # Initialize LLM polisher for dictation accuracy (if enabled)
        use_llm_polish = self.config.get("use_llm_polish", True)
        if use_llm_polish:
            self.polisher = TranscriptionPolisher(
                ollama_url=self.config.get("ollama_url", "http://localhost:11434"),
                model=self.config.get("llm_polish_model", "qwen2.5:7b-instruct-q4_0"),
                timeout=self.config.get("llm_polish_timeout", 3.0),
                enabled=True,
            )
            logger.info("LLM polish for dictation: enabled")
        else:
            self.polisher = None

        # Initialize clipboard monitor (if enabled)
        clipboard_enabled = self.config.get("clipboard_history_enabled", True)
        if clipboard_enabled:
            self.clipboard_monitor = ClipboardMonitor(
                max_items=self.config.get("clipboard_history_max_items", 5),
            )
        else:
            self.clipboard_monitor = None

        # State tracking
        self.dictation_active = False
        self.assistant_active = False
        self.running = True

        # State file for GUI overlay communication
        self.state_file = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "synthia-state.json"
        )
        # History file for voice transcription history
        self.history_file = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "synthia-history.json"
        )
        # Signal file for config reload (used by GUI to trigger live hotkey updates)
        self.reload_signal_file = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "synthia-reload-config"
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
            dictation_key_string=self.config["dictation_key"],
            assistant_key_string=self.config["assistant_key"],
        )

        # Display friendly key names
        dictation_display = self.config["dictation_key"].replace("Key.", "").replace("_", " ").title()
        assistant_display = self.config["assistant_key"].replace("Key.", "").replace("_", " ").title()

        logger.info("Display server: %s", get_display_server())
        logger.info("Dictation key: %s (hold to dictate)", dictation_display)
        logger.info("Assistant key: %s (hold to ask AI)", assistant_display)
        logger.info("Synthia ready!")

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
        except Exception as e:
            logger.debug("Could not update state file: %s", e)

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
            logger.debug("Could not save history: %s", e)

    def _on_quit(self):
        """Handle quit from tray icon."""
        self.running = False

    def _watch_config_reload(self):
        """Watch for config reload signal file and update hotkeys dynamically."""
        while self.running:
            try:
                if os.path.exists(self.reload_signal_file):
                    # Remove the signal file
                    os.remove(self.reload_signal_file)

                    # Reload config
                    new_config = load_config()
                    new_dictation_key = new_config["dictation_key"]
                    new_assistant_key = new_config["assistant_key"]

                    # Update the hotkey listener
                    self.hotkey_listener.update_keys(new_dictation_key, new_assistant_key)

                    # Update our stored config
                    self.config = new_config

                    logger.info("Hotkeys updated dynamically")
            except Exception as e:
                logger.warning("Config reload error: %s", e)

            time.sleep(0.5)  # Check twice per second

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
            logger.error("Could not start recording: %s", e)
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
                    # LLM polish for improved accuracy (optional)
                    if self.polisher:
                        text = self.polisher.polish(text)
                    # Apply word replacements to fix common misrecognitions
                    text = apply_word_replacements(text, self.config)
                    type_text(text)
                    self._save_to_history(text, "dictation")
                    if self.config.get("show_notifications", True):
                        notify_dictation(text)

            self._update_state("ready")
            if self.tray:
                self.tray.set_status(Status.READY)

        except Exception as e:
            logger.error("Error: %s", e)
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
            logger.error("Could not start recording: %s", e)
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
                    logger.info("Command: %s", text)

                    # Process with Claude
                    response = self.assistant.process(text)

                    # Speak the response
                    if response.get("speech"):
                        self.tts.speak(response["speech"])
                        self._save_to_history(text, "assistant", response["speech"])
                        if self.config.get("show_notifications", True):
                            notify_assistant(response["speech"])

                    # Execute any actions
                    logger.debug("Actions received: %s", response.get("actions"))
                    if response.get("actions"):
                        results, command_output = execute_actions(response["actions"])
                        logger.debug("Action results: %s", results)

                        # If a command returned output, speak it
                        if command_output:
                            self.tts.speak(command_output)

            self._update_state("ready")
            if self.tray:
                self.tray.set_status(Status.READY)

        except Exception as e:
            logger.error("Error: %s", e)
            self.sounds.play_error()
            if self.config.get("show_notifications", True):
                notify_error(str(e))
            if self.tray:
                self.tray.set_status(Status.READY)

    def run(self):
        """Run the main keyboard listener loop."""
        logger.info("Use Ctrl+C to exit")

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            logger.info("Interrupted, exiting...")
            self.running = False
            self.hotkey_listener.stop()

        signal.signal(signal.SIGINT, signal_handler)

        # Start config watcher thread (for live hotkey updates from GUI)
        config_watcher = threading.Thread(target=self._watch_config_reload, daemon=True)
        config_watcher.start()

        # Start clipboard monitor (if enabled)
        if self.clipboard_monitor:
            self.clipboard_monitor.start()
            logger.info("Clipboard monitor started")

        # Start the hotkey listener (auto-detects Wayland vs X11)
        self.hotkey_listener.start()
        self.hotkey_listener.join()

        # Cleanup
        if self.clipboard_monitor:
            self.clipboard_monitor.stop()
        if self.tray:
            self.tray.stop()
        self.sounds.cleanup()


def handle_memory_command(args: list[str]):
    """Handle memory subcommand.

    Usage:
        synthia memory           - Launch TUI dashboard
        synthia memory recall <tags>    - Quick recall by tags
        synthia memory search <query>   - Text search
        synthia memory stats     - Show statistics
        synthia memory tags      - List all tags
    """
    from synthia.memory import get_memory_system, recall, search

    if not args or args[0] == "tui":
        # Launch TUI dashboard
        try:
            from synthia.memory_tui import main as run_tui
            run_tui()
        except ImportError:
            print("TUI requires textual. Install with: pip install textual")
            return
        return

    subcmd = args[0]

    if subcmd == "recall":
        if len(args) < 2:
            print("Usage: synthia memory recall <tags>")
            print("Example: synthia memory recall frontend,react")
            return

        tags = [t.strip() for t in args[1].split(",")]
        entries = recall(tags)

        if not entries:
            print("No memories found for those tags")
            return

        print(f"\n=== Memory Recall: {', '.join(tags)} ===\n")
        for entry in entries:
            print(entry.format_display())
            print("-" * 40)
        print(f"\n=== Found {len(entries)} entries ===")

    elif subcmd == "search":
        if len(args) < 2:
            print("Usage: synthia memory search <query>")
            return

        query = " ".join(args[1:])
        entries = search(query)

        if not entries:
            print(f"No memories found for '{query}'")
            return

        print(f"\n=== Search: {query} ===\n")
        for entry in entries:
            print(entry.format_display())
            print("-" * 40)
        print(f"\n=== Found {len(entries)} entries ===")

    elif subcmd == "stats":
        mem = get_memory_system()
        counts = mem.list_categories()
        total = sum(counts.values())

        print("\n=== Memory Statistics ===\n")
        print(f"Total entries: {total}")
        for cat, count in counts.items():
            print(f"  {cat}: {count}")

    elif subcmd == "tags":
        mem = get_memory_system()
        tags = mem.list_all_tags()

        print("\n=== All Tags (by usage) ===\n")
        for tag, count in tags.items():
            print(f"  {tag}: {count}")

    else:
        print(f"Unknown memory subcommand: {subcmd}")
        print("\nUsage:")
        print("  synthia memory           - Launch TUI dashboard")
        print("  synthia memory recall <tags>  - Quick recall by tags")
        print("  synthia memory search <query> - Text search")
        print("  synthia memory stats     - Show statistics")
        print("  synthia memory tags      - List all tags")


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Show audio devices for debugging
    if "--list-devices" in sys.argv:
        list_audio_devices()
        return

    # Handle memory subcommand
    if len(sys.argv) > 1 and sys.argv[1] == "memory":
        handle_memory_command(sys.argv[2:])
        return

    # Show help
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("\nSubcommands:")
        print("  synthia memory    - Memory system TUI and CLI")
        print("  synthia --list-devices  - Show audio devices")
        return

    try:
        app = Synthia()
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting...")
    except Exception as e:
        logger.error("Error: %s", e)
        raise


if __name__ == "__main__":
    main()
