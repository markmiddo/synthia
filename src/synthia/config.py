"""Configuration loading for Synthia."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Type alias for config dictionary
ConfigDict = dict[str, Any]

DEFAULT_CONFIG: ConfigDict = {
    # Hotkeys
    "dictation_key": "Key.ctrl_r",
    "assistant_key": "Key.alt_r",
    # Speech Recognition
    "language": "en-US",
    "sample_rate": 16000,
    # Text-to-Speech
    "tts_voice": "en-US-Neural2-J",
    "tts_speed": 1.0,
    # Assistant
    "assistant_model": "claude-sonnet-4-20250514",
    "conversation_memory": 10,
    "assistant_personality": "You are a helpful Linux assistant. Keep responses brief and friendly.",
    # Credentials
    "google_credentials": "~/.config/synthia/google-creds.json",
    "anthropic_api_key": "~/.config/synthia/anthropic-key.txt",
    # UI
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
    # Telegram remote access (must be configured by user)
    "telegram_bot_token": "",  # Get from @BotFather
    "telegram_allowed_users": [],  # List of Telegram user IDs
    # Web search (Tavily)
    "tavily_api_key": "",  # Get from tavily.com
    # LLM Polish for dictation accuracy
    "use_llm_polish": True,  # Enable LLM review of transcriptions
    "llm_polish_model": "qwen2.5:7b-instruct-q4_0",  # Model for polishing
    "llm_polish_timeout": 3.0,  # Timeout in seconds (fail-safe to original)
    # Clipboard Manager
    "clipboard_history_enabled": True,  # Enable clipboard history tracking
    "clipboard_history_max_items": 5,  # Number of items to remember
    # Memory System
    "memory_enabled": True,  # Enable memory system integration
    "memory_auto_retrieve": False,  # Auto-retrieve relevant memories in dev mode
    "memory_dir": "~/.claude/memory",  # Memory storage directory
    # Word replacements for dictation (fixes common Whisper misrecognitions)
    "word_replacements": {
        "Cynthia": "Synthia",
        "cynthia": "synthia",
    },
}

CONFIG_PATH = Path.home() / ".config" / "synthia" / "config.yaml"


def load_config() -> ConfigDict:
    """Load configuration from YAML file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            user_config = yaml.safe_load(f) or {}
            config.update(user_config)

    return config


def get_google_credentials_path(config: ConfigDict) -> str:
    """Get the expanded path to Google credentials."""
    return os.path.expanduser(config["google_credentials"])


def get_anthropic_api_key(config: ConfigDict) -> str:
    """Load the Anthropic API key from file."""
    key_path = os.path.expanduser(config["anthropic_api_key"])
    with open(key_path) as f:
        return f.read().strip()


def apply_word_replacements(text: str, config: ConfigDict) -> str:
    """Apply word replacements to fix common transcription errors.

    Args:
        text: The transcribed text from Whisper
        config: Configuration dictionary containing word_replacements

    Returns:
        Text with all configured word replacements applied
    """
    replacements = config.get("word_replacements", {})
    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)
    return text
