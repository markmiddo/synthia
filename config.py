"""Configuration loading for LinuxVoice."""

import os
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    "dictation_key": "Key.ctrl_r",
    "assistant_key": "Key.alt_r",
    "language": "en-US",
    "sample_rate": 16000,
    "tts_voice": "en-US-Neural2-J",
    "tts_speed": 1.0,
    "assistant_model": "claude-sonnet-4-20250514",
    "conversation_memory": 10,
    "assistant_personality": "You are a helpful Linux assistant. Keep responses brief and friendly.",
    "google_credentials": "~/.config/linuxvoice/google-creds.json",
    "anthropic_api_key": "~/.config/linuxvoice/anthropic-key.txt",
    "show_notifications": True,
    "play_sound_on_record": True,
    # Local model options
    "use_local_stt": False,
    "use_local_llm": False,
    "use_local_tts": False,
    "local_stt_model": "small",  # tiny, base, small, medium, large
    "local_llm_model": "qwen2.5:7b-instruct-q4_0",
    "local_tts_voice": "~/.local/share/piper-voices/en_US-amy-medium.onnx",
    "ollama_url": "http://localhost:11434",
}

CONFIG_PATH = Path.home() / ".config" / "linuxvoice" / "config.yaml"


def load_config() -> dict:
    """Load configuration from YAML file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            user_config = yaml.safe_load(f) or {}
            config.update(user_config)

    return config


def get_google_credentials_path(config: dict) -> str:
    """Get the expanded path to Google credentials."""
    return os.path.expanduser(config["google_credentials"])


def get_anthropic_api_key(config: dict) -> str:
    """Load the Anthropic API key from file."""
    key_path = os.path.expanduser(config["anthropic_api_key"])
    with open(key_path, "r") as f:
        return f.read().strip()
