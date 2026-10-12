#!/usr/bin/env python3
"""Synthia - Voice Dictation + AI Assistant for Linux.

Usage:
    Hold Right Ctrl - Dictation mode (speech to text)
    Hold Right Alt  - Assistant mode (AI voice assistant)
    Say "Hey Linux" - Wake word (when enabled)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Optional

from synthia.acks import AckBank
from synthia.assistant import Assistant
from synthia.audio import AudioRecorder, list_audio_devices
from synthia.brain_client import DEFAULT_PORT, BrainClient
from synthia.clipboard_monitor import ClipboardMonitor
from synthia.commands import execute_actions
from synthia.config import (
    apply_word_replacements,
    get_anthropic_api_key,
    get_google_credentials_path,
    load_config,
)
from synthia.desk_voice import DeskVoice
from synthia.display import get_display_server, is_wayland
from synthia.hotkeys import DISABLED_HOTKEY, create_hotkey_listener
from synthia.indicator import Status, TrayIndicator
from synthia.llm_polish import TranscriptionPolisher
from synthia.murmur_listener import UNAVAILABLE_LINE, MurmurListener
from synthia.notifications import notify_assistant, notify_dictation, notify_error, notify_ready
from synthia.output import type_text
from synthia.sounds import SoundEffects
from synthia.transcribe import Transcriber
from synthia.tts import TextToSpeech

logger = logging.getLogger(__name__)

# DeskVoice state -> tray status (brain mode); the tray follows the same reports as the state file.
_DESK_TRAY_STATUS = {
    "thinking": Status.THINKING,
    "speaking": Status.ASSISTANT,
    "ready": Status.READY,
}


def needs_keyboard(dictation_key: str, assistant_key: str) -> bool:
    """Whether Synthia has any hotkey of its own to listen for."""
    return dictation_key != DISABLED_HOTKEY or assistant_key != DISABLED_HOTKEY


def use_murmur_stt(config: dict[str, Any]) -> bool:
    """Murmur hears the desk assistant key (only meaningful with the brain backend)."""
    return config.get("assistant_backend") == "brain" and config.get("stt_source") == "murmur"


def needs_local_stt(config: dict[str, Any]) -> bool:
    """Whether Synthia must record and transcribe itself (so Whisper is worth loading)."""
    if not use_murmur_stt(config):
        return True
    return bool(config.get("dictation_key", "none") != "none")


class Synthia:
    """Main Synthia application."""

    def __init__(self) -> None:
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

        # Murmur hears the desk assistant key; with no dictation either, Synthia never
        # records or transcribes, so the microphone and Whisper stay untouched.
        self.murmur_mode = use_murmur_stt(self.config)
        self.recorder: Optional[AudioRecorder] = None
        self.transcriber: Optional[Transcriber] = None
        if needs_local_stt(self.config):
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
                "Transcriber initialized (%s)",
                "local Whisper" if use_local_stt else "Google Cloud",
            )
        else:
            logger.info("Speech-to-text: Murmur (no local recorder or Whisper)")

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

        # Desk voice through the synthia-brain websocket (assistant_backend: brain)
        self.desk_voice: Optional[DeskVoice] = None
        if self.config.get("assistant_backend", "local") == "brain":
            desk_port = int(self.config.get("brain_desk_port", DEFAULT_PORT))
            ack_source = None
            if not use_local_tts:
                # Short acknowledgements, rendered once with her voice, so she answers at once.
                acks = AckBank(
                    self.config["tts_voice"], self.tts.synthesize_to_file, self.config["tts_speed"]
                )
                acks.start()
                ack_source = acks.next
            self.desk_voice = DeskVoice(
                client_factory=lambda on_frame: BrainClient(on_frame, port=desk_port),
                # Mark asked; answer even when background speech is muted.
                speak=lambda text: self.tts.speak(text, ignore_mute=True),
                stop_speaking=self.tts.cancel,
                on_state=self._on_desk_state,
                ack_source=ack_source,
                play_ack=(lambda path: self.tts.play_file(path, ignore_mute=True)),
            )
            self.tts.on_play_start = self.desk_voice.mark_audio_start
            logger.info("Assistant: synthia-brain desk (port %d)", desk_port)

        # Initialize LLM polisher for dictation accuracy (if enabled)
        use_llm_polish = self.config.get("use_llm_polish", True)
        self.polisher: Optional[TranscriptionPolisher] = None
        if use_llm_polish:
            self.polisher = TranscriptionPolisher(
                ollama_url=self.config.get("ollama_url", "http://localhost:11434"),
                model=self.config.get("llm_polish_model", "qwen2.5:7b-instruct-q4_0"),
                timeout=self.config.get("llm_polish_timeout", 3.0),
                enabled=True,
            )
            logger.info("LLM polish for dictation: enabled")

        # Initialize clipboard monitor (if enabled)
        clipboard_enabled = self.config.get("clipboard_history_enabled", True)
        self.clipboard_monitor: Optional[ClipboardMonitor] = None
        if clipboard_enabled:
            self.clipboard_monitor = ClipboardMonitor(
                max_items=self.config.get("clipboard_history_max_items", 5),
            )

        # State tracking
        self.dictation_active = False
        self.assistant_active = False
        self.running = True
        # Murmur's assistant key label for the HUD: None = unknown, "" = no key set.
        self.talk_key: Optional[str] = None
        self._last_status = "ready"

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

        # Murmur owns the assistant key in murmur mode: Synthia registers none of its own.
        self.assistant_key_string = (
            DISABLED_HOTKEY if self.murmur_mode else self.config["assistant_key"]
        )

        # Parse hotkeys from config (for X11/pynput)
        self.dictation_key = self._parse_key(self.config["dictation_key"])
        self.assistant_key = self._parse_key(self.assistant_key_string)

        # Create hotkey listener (auto-detects Wayland vs X11)
        self.hotkey_listener = create_hotkey_listener(
            on_dictation_press=self._on_dictation_press,
            on_dictation_release=self._on_dictation_release,
            on_assistant_press=self._on_assistant_press,
            on_assistant_release=self._on_assistant_release,
            dictation_key=self.dictation_key,
            assistant_key=self.assistant_key,
            dictation_key_string=self.config["dictation_key"],
            assistant_key_string=self.assistant_key_string,
        )

        self.murmur: Optional[MurmurListener] = None
        if self.murmur_mode and self.desk_voice is not None:
            self.murmur = MurmurListener(
                on_started=self._on_murmur_started,
                on_transcribed=self._on_murmur_transcribed,
                on_cancelled=self._on_murmur_cancelled,
                on_unavailable=self._on_murmur_unavailable,
                on_hotkey=self._on_murmur_hotkey,
            )

        # Display friendly key names
        dictation_display = (
            self.config["dictation_key"].replace("Key.", "").replace("_", " ").title()
            if self.config["dictation_key"] != "none"
            else "off"
        )
        assistant_display = (
            "Murmur"
            if self.murmur_mode
            else self.config["assistant_key"].replace("Key.", "").replace("_", " ").title()
        )

        logger.info("Display server: %s", get_display_server())
        logger.info("Dictation key: %s (hold to dictate)", dictation_display)
        logger.info("Assistant key: %s (hold to ask AI)", assistant_display)
        logger.info("Synthia ready!")

        # Show notification
        if self.config.get("show_notifications", True):
            notify_ready()

    def _parse_key(self, key_string: str) -> Any:
        """Parse a key string like 'Key.ctrl_r' to a pynput Key."""
        from pynput.keyboard import Key

        if key_string.startswith("Key."):
            key_name = key_string[4:]
            return getattr(Key, key_name)
        return key_string

    def _update_state(self, status: str) -> None:
        """Update state file for GUI overlay communication."""
        try:
            self._last_status = status
            state = {
                "status": status,
                "recording": status == "recording",
                "stt_source": "murmur" if self.murmur_mode else "synthia",
                "talk_key": self.talk_key,
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f)
        except Exception as e:
            logger.debug("Could not update state file: %s", e)

    def _on_desk_state(self, status: str) -> None:
        """Brain-mode state from DeskVoice: the state file and the tray move together."""
        self._update_state(status)
        if self.tray is not None:
            self.tray.set_status(_DESK_TRAY_STATUS.get(status, Status.READY))

    def _save_to_history(self, text: str, mode: str, response: Optional[str] = None) -> None:
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

    def _on_quit(self) -> None:
        """Handle quit from tray icon."""
        self.running = False

    def _watch_config_reload(self) -> None:
        """Watch for config reload signal file and update hotkeys dynamically."""
        while self.running:
            try:
                if os.path.exists(self.reload_signal_file):
                    # Remove the signal file
                    os.remove(self.reload_signal_file)

                    # Reload config
                    new_config = load_config()
                    new_dictation_key = new_config["dictation_key"]
                    new_assistant_key = (
                        DISABLED_HOTKEY if self.murmur_mode else new_config["assistant_key"]
                    )

                    # Update the hotkey listener
                    self.hotkey_listener.update_keys(new_dictation_key, new_assistant_key)

                    # Update our stored config
                    self.config = new_config

                    logger.info("Hotkeys updated dynamically")
            except Exception as e:
                logger.warning("Config reload error: %s", e)

            time.sleep(0.5)  # Check twice per second

    def _on_dictation_press(self) -> None:
        """Handle dictation key press (Right Ctrl)."""
        if not self.running or self.dictation_active or self.assistant_active:
            return
        if self.recorder is None:
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

    def _on_dictation_release(self) -> None:
        """Handle dictation key release (Right Ctrl)."""
        if not self.running or not self.dictation_active:
            return

        try:
            self.dictation_active = False
            self._update_state("thinking")
            self.sounds.play_stop()
            if self.tray:
                self.tray.set_status(Status.THINKING)

            audio_data = self.recorder.stop_recording() if self.recorder else None

            if audio_data and self.transcriber:
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
            self._update_state("ready")
            if self.tray:
                self.tray.set_status(Status.READY)

    def _on_assistant_press(self) -> None:
        """Handle assistant key press (Right Alt)."""
        if not self.running or self.assistant_active or self.dictation_active:
            return
        if self.recorder is None:
            return

        # A new press while she is talking cuts her off, then records the next question.
        if self.desk_voice is not None:
            self.desk_voice.begin_utterance()

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
            if self.desk_voice is not None:
                self.desk_voice.end_utterance()

    def _on_assistant_release(self) -> None:
        """Handle assistant key release (Right Alt)."""
        if not self.running or not self.assistant_active:
            return

        released_at = time.monotonic()
        try:
            self.assistant_active = False
            self._update_state("thinking")
            self.sounds.play_stop()
            if self.tray:
                self.tray.set_status(Status.THINKING)

            audio_data = self.recorder.stop_recording() if self.recorder else None

            if audio_data and self.transcriber:
                # Transcribe the command
                text = self.transcriber.transcribe(audio_data)

                if text:
                    logger.info("Command: %s", text)

                    if self.desk_voice is not None:
                        # The brain streams the reply; DeskVoice speaks it as it arrives.
                        self.desk_voice.ask(text, released_at=released_at)
                        self._save_to_history(text, "assistant")
                        # DeskVoice reports thinking, speaking and ready (state file and
                        # tray) as the reply plays.
                        return

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

            if self.desk_voice is not None:
                # Nothing heard: no turn starts, so hand state reporting back to DeskVoice.
                self.desk_voice.end_utterance()
                return

            self._update_state("ready")
            if self.tray:
                self.tray.set_status(Status.READY)

        except Exception as e:
            logger.error("Error: %s", e)
            self.sounds.play_error()
            if self.config.get("show_notifications", True):
                notify_error(str(e))
            if self.desk_voice is not None:
                self.desk_voice.end_utterance()
            else:
                self._update_state("ready")
                if self.tray:
                    self.tray.set_status(Status.READY)

    # -- Murmur (stt_source: murmur) ------------------------------------------------

    def _on_murmur_started(self) -> None:
        """Murmur began recording the assistant key: same as pressing it."""
        if not self.running or self.desk_voice is None:
            return
        # She stops talking so Mark can speak (a pending yes/no is kept alive).
        self.desk_voice.begin_utterance()
        self.assistant_active = True
        self._update_state("recording")
        if self.tray:
            self.tray.set_status(Status.RECORDING)
        # No start sound: Murmur plays its own.

    def _on_murmur_transcribed(self, text: str, received_at: float) -> None:
        """Murmur finished: same as releasing the key with a transcript (or nothing heard)."""
        if not self.running or self.desk_voice is None:
            return
        self.assistant_active = False
        text = (text or "").strip()
        if not text:
            self.desk_voice.end_utterance()
            return
        logger.info("Command: %s", text)
        self.desk_voice.ask(text, released_at=received_at)
        self._save_to_history(text, "assistant")

    def _on_murmur_cancelled(self) -> None:
        """Murmur dropped the recording (tap too short, error, paused): nothing to answer."""
        self.assistant_active = False
        if self.desk_voice is not None:
            self.desk_voice.end_utterance()

    def _on_murmur_unavailable(self) -> None:
        """Murmur is not on the bus: say so once (the listener keeps retrying)."""
        self.assistant_active = False
        if self.desk_voice is not None:
            self.desk_voice.end_utterance()
        threading.Thread(
            target=lambda: self.tts.speak(UNAVAILABLE_LINE, ignore_mute=True),
            name="murmur-notice",
            daemon=True,
        ).start()

    def _on_murmur_hotkey(self, label: Optional[str]) -> None:
        """Remember Murmur's assistant key so the HUD can name it."""
        if label == self.talk_key:
            return
        self.talk_key = label
        self._update_state(self._last_status)

    def run(self) -> None:
        """Run the main keyboard listener loop."""
        logger.info("Use Ctrl+C to exit")

        # Handle Ctrl+C gracefully
        stopped = threading.Event()

        def signal_handler(sig, frame):
            logger.info("Interrupted, exiting...")
            self.running = False
            stopped.set()
            self.hotkey_listener.stop()

        signal.signal(signal.SIGINT, signal_handler)

        # Start config watcher thread (for live hotkey updates from GUI)
        config_watcher = threading.Thread(target=self._watch_config_reload, daemon=True)
        config_watcher.start()

        # Start clipboard monitor (if enabled)
        if self.clipboard_monitor:
            self.clipboard_monitor.start()
            logger.info("Clipboard monitor started")

        if self.murmur:
            self.murmur.start()

        if needs_keyboard(self.config["dictation_key"], self.assistant_key_string):
            # Start the hotkey listener (auto-detects Wayland vs X11)
            self.hotkey_listener.start()
            self.hotkey_listener.join()
        else:
            # Murmur hears both keys: there is no keyboard for Synthia to watch.
            logger.info("No Synthia hotkeys (Murmur owns them); waiting for Murmur")
            stopped.wait()

        # Cleanup
        if self.murmur:
            self.murmur.stop()
        if self.clipboard_monitor:
            self.clipboard_monitor.stop()
        if self.tray:
            self.tray.stop()
        self.sounds.cleanup()


def handle_memory_command(args: list[str]) -> None:
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
        all_tags = mem.list_all_tags()

        print("\n=== All Tags (by usage) ===\n")
        for tag, count in all_tags.items():
            print(f"  {tag}: {count}")

    else:
        print(f"Unknown memory subcommand: {subcmd}")
        print("\nUsage:")
        print("  synthia memory           - Launch TUI dashboard")
        print("  synthia memory recall <tags>  - Quick recall by tags")
        print("  synthia memory search <query> - Text search")
        print("  synthia memory stats     - Show statistics")
        print("  synthia memory tags      - List all tags")


def main() -> None:
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
