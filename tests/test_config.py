"""Tests for synthia.config module."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synthia import config
from synthia.config import (
    DEFAULT_CONFIG,
    apply_word_replacements,
    get_anthropic_api_key,
    get_google_credentials_path,
    load_config,
)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_returns_defaults_when_no_config_file(self, monkeypatch, tmp_path):
        """load_config returns default values when config file does not exist."""
        non_existent = tmp_path / "does_not_exist" / "config.yaml"
        monkeypatch.setattr(config, "CONFIG_PATH", non_existent)

        result = load_config()

        assert result == DEFAULT_CONFIG

    def test_merges_user_overrides_from_file(self, monkeypatch, tmp_path):
        """load_config merges user config values over defaults."""
        config_file = tmp_path / "config.yaml"
        user_config = {
            "language": "fr-FR",
            "sample_rate": 44100,
            "tts_speed": 1.5,
        }
        config_file.write_text(yaml.dump(user_config))
        monkeypatch.setattr(config, "CONFIG_PATH", config_file)

        result = load_config()

        assert result["language"] == "fr-FR"
        assert result["sample_rate"] == 44100
        assert result["tts_speed"] == 1.5
        # Defaults should still be present
        assert result["dictation_key"] == "Key.ctrl_r"
        assert result["assistant_key"] == "Key.alt_r"

    def test_handles_empty_yaml_file(self, monkeypatch, tmp_path):
        """load_config handles empty yaml file gracefully."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        monkeypatch.setattr(config, "CONFIG_PATH", config_file)

        result = load_config()

        assert result == DEFAULT_CONFIG


class TestApplyWordReplacements:
    """Tests for apply_word_replacements function."""

    def test_substitutes_correctly(self):
        """apply_word_replacements replaces matching words."""
        cfg = {"word_replacements": {"Cynthia": "Synthia", "cynthia": "synthia"}}
        text = "Hello Cynthia, this is cynthia speaking."

        result = apply_word_replacements(text, cfg)

        assert result == "Hello Synthia, this is synthia speaking."

    def test_with_empty_replacements(self):
        """apply_word_replacements returns text unchanged with empty replacements."""
        cfg = {"word_replacements": {}}
        text = "Hello Cynthia"

        result = apply_word_replacements(text, cfg)

        assert result == "Hello Cynthia"

    def test_with_no_matches(self):
        """apply_word_replacements returns text unchanged when no matches found."""
        cfg = {"word_replacements": {"foo": "bar", "baz": "qux"}}
        text = "Hello world, nothing to replace here."

        result = apply_word_replacements(text, cfg)

        assert result == "Hello world, nothing to replace here."


class TestGetGoogleCredentialsPath:
    """Tests for get_google_credentials_path function."""

    def test_expands_tilde(self):
        """get_google_credentials_path expands ~ to home directory."""
        cfg = {"google_credentials": "~/.config/synthia/google-creds.json"}

        result = get_google_credentials_path(cfg)

        assert result == str(Path.home() / ".config" / "synthia" / "google-creds.json")


class TestGetAnthropicApiKey:
    """Tests for get_anthropic_api_key function."""

    def test_reads_file_content(self, tmp_path):
        """get_anthropic_api_key reads and strips file content."""
        key_file = tmp_path / "anthropic-key.txt"
        key_file.write_text("sk-ant-api03-secret-key-12345\n")
        cfg = {"anthropic_api_key": str(key_file)}

        result = get_anthropic_api_key(cfg)

        assert result == "sk-ant-api03-secret-key-12345"


class TestDefaultConfig:
    """Tests for DEFAULT_CONFIG structure."""

    def test_has_expected_keys(self):
        """DEFAULT_CONFIG contains all expected configuration keys."""
        expected_keys = {
            "dictation_key",
            "assistant_key",
            "language",
            "sample_rate",
            "tts_voice",
            "tts_speed",
            "assistant_model",
            "conversation_memory",
            "assistant_personality",
            "google_credentials",
            "anthropic_api_key",
            "show_notifications",
            "play_sound_on_record",
            "use_local_stt",
            "use_local_llm",
            "use_local_tts",
            "local_stt_model",
            "local_llm_model",
            "local_tts_voice",
            "ollama_url",
            "telegram_bot_token",
            "telegram_allowed_users",
            "tavily_api_key",
            "use_llm_polish",
            "llm_polish_model",
            "llm_polish_timeout",
            "clipboard_history_enabled",
            "clipboard_history_max_items",
            "memory_enabled",
            "memory_auto_retrieve",
            "memory_dir",
            "word_replacements",
        }

        assert set(DEFAULT_CONFIG.keys()) == expected_keys
