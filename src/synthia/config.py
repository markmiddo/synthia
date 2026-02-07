"""Configuration loading for Synthia."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

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

# Valid values for constrained config keys
VALID_HOTKEYS = {
    "Key.ctrl_r", "Key.ctrl_l", "Key.alt_r", "Key.alt_l",
    "Key.shift_r", "Key.shift_l",
}
VALID_SAMPLE_RATES = {8000, 16000, 22050, 44100, 48000}
VALID_STT_MODELS = {"tiny", "base", "small", "medium", "large"}

# Keys that must be boolean
_BOOLEAN_KEYS = {
    "show_notifications", "play_sound_on_record",
    "use_local_stt", "use_local_llm", "use_local_tts",
    "use_llm_polish", "clipboard_history_enabled",
    "memory_enabled", "memory_auto_retrieve",
}


def validate_config(config: ConfigDict) -> list[str]:
    """Validate configuration values and return a list of warnings.

    Checks types, ranges, and known values. Never crashes on bad config —
    returns warnings so the caller can log them and continue.
    """
    warnings: list[str] = []

    # Hotkeys
    for key in ("dictation_key", "assistant_key"):
        val = config.get(key)
        if val is not None and val not in VALID_HOTKEYS:
            warnings.append(
                f"{key}={val!r} is not a known hotkey. "
                f"Valid: {', '.join(sorted(VALID_HOTKEYS))}"
            )

    # Sample rate
    sr = config.get("sample_rate")
    if sr is not None and sr not in VALID_SAMPLE_RATES:
        warnings.append(
            f"sample_rate={sr} is not a standard rate. "
            f"Valid: {sorted(VALID_SAMPLE_RATES)}"
        )

    # TTS speed
    speed = config.get("tts_speed")
    if speed is not None and not (0.25 <= speed <= 4.0):
        warnings.append(f"tts_speed={speed} is out of range (0.25–4.0)")

    # Positive integers
    for key in ("conversation_memory", "clipboard_history_max_items"):
        val = config.get(key)
        if val is not None and (not isinstance(val, int) or val <= 0):
            warnings.append(f"{key}={val!r} must be a positive integer")

    # LLM polish timeout
    timeout = config.get("llm_polish_timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        warnings.append(f"llm_polish_timeout={timeout!r} must be a positive number")

    # Boolean flags
    for key in _BOOLEAN_KEYS:
        val = config.get(key)
        if val is not None and not isinstance(val, bool):
            warnings.append(f"{key}={val!r} must be true or false")

    # Local STT model
    model = config.get("local_stt_model")
    if model is not None and model not in VALID_STT_MODELS:
        warnings.append(
            f"local_stt_model={model!r} is not valid. "
            f"Valid: {', '.join(sorted(VALID_STT_MODELS))}"
        )

    # Ollama URL
    url = config.get("ollama_url")
    if url and not (url.startswith("http://") or url.startswith("https://")):
        warnings.append(f"ollama_url={url!r} must start with http:// or https://")

    # Unknown keys
    unknown = set(config.keys()) - set(DEFAULT_CONFIG.keys())
    if unknown:
        warnings.append(
            f"Unknown config keys (possible typos): {', '.join(sorted(unknown))}"
        )

    return warnings


def load_config() -> ConfigDict:
    """Load configuration from YAML file, falling back to defaults.

    Validates the merged config and logs warnings for any issues found.
    """
    config = DEFAULT_CONFIG.copy()

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            user_config = yaml.safe_load(f) or {}
            config.update(user_config)

    for warning in validate_config(config):
        logger.warning("Config: %s", warning)

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
