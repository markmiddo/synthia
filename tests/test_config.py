"""Tests for synthia.config module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synthia import config
from synthia.config import (
    DEFAULT_CONFIG,
    VALID_HOTKEYS,
    VALID_SAMPLE_RATES,
    VALID_STT_MODELS,
    apply_word_replacements,
    get_anthropic_api_key,
    get_google_credentials_path,
    load_config,
    validate_config,
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


class TestValidateConfig:
    """Tests for validate_config function."""

    def test_default_config_passes_validation(self):
        """DEFAULT_CONFIG produces zero warnings."""
        warnings = validate_config(DEFAULT_CONFIG)
        assert warnings == []

    def test_warns_on_invalid_hotkey(self):
        """Invalid hotkey value produces a warning."""
        cfg = {**DEFAULT_CONFIG, "dictation_key": "Key.f12"}
        warnings = validate_config(cfg)
        assert any("dictation_key" in w for w in warnings)

    def test_accepts_valid_hotkeys(self):
        """All VALID_HOTKEYS are accepted without warnings."""
        for key in VALID_HOTKEYS:
            cfg = {**DEFAULT_CONFIG, "dictation_key": key}
            warnings = validate_config(cfg)
            assert not any("dictation_key" in w for w in warnings)

    def test_warns_on_invalid_sample_rate(self):
        """Non-standard sample rate produces a warning."""
        cfg = {**DEFAULT_CONFIG, "sample_rate": 9999}
        warnings = validate_config(cfg)
        assert any("sample_rate" in w for w in warnings)

    def test_accepts_valid_sample_rates(self):
        """All VALID_SAMPLE_RATES pass without warnings."""
        for rate in VALID_SAMPLE_RATES:
            cfg = {**DEFAULT_CONFIG, "sample_rate": rate}
            warnings = validate_config(cfg)
            assert not any("sample_rate" in w for w in warnings)

    def test_warns_on_tts_speed_too_low(self):
        """TTS speed below 0.25 produces a warning."""
        cfg = {**DEFAULT_CONFIG, "tts_speed": 0.1}
        warnings = validate_config(cfg)
        assert any("tts_speed" in w for w in warnings)

    def test_warns_on_tts_speed_too_high(self):
        """TTS speed above 4.0 produces a warning."""
        cfg = {**DEFAULT_CONFIG, "tts_speed": 5.0}
        warnings = validate_config(cfg)
        assert any("tts_speed" in w for w in warnings)

    def test_accepts_tts_speed_boundaries(self):
        """TTS speed at boundaries (0.25 and 4.0) is valid."""
        for speed in (0.25, 4.0):
            cfg = {**DEFAULT_CONFIG, "tts_speed": speed}
            warnings = validate_config(cfg)
            assert not any("tts_speed" in w for w in warnings)

    def test_warns_on_zero_conversation_memory(self):
        """Zero conversation_memory produces a warning."""
        cfg = {**DEFAULT_CONFIG, "conversation_memory": 0}
        warnings = validate_config(cfg)
        assert any("conversation_memory" in w for w in warnings)

    def test_warns_on_negative_clipboard_max(self):
        """Negative clipboard_history_max_items produces a warning."""
        cfg = {**DEFAULT_CONFIG, "clipboard_history_max_items": -1}
        warnings = validate_config(cfg)
        assert any("clipboard_history_max_items" in w for w in warnings)

    def test_warns_on_non_positive_llm_timeout(self):
        """Zero or negative llm_polish_timeout produces a warning."""
        cfg = {**DEFAULT_CONFIG, "llm_polish_timeout": 0}
        warnings = validate_config(cfg)
        assert any("llm_polish_timeout" in w for w in warnings)

    def test_warns_on_non_bool_flag(self):
        """Non-boolean value for a boolean flag produces a warning."""
        cfg = {**DEFAULT_CONFIG, "use_local_stt": "yes"}
        warnings = validate_config(cfg)
        assert any("use_local_stt" in w for w in warnings)

    def test_warns_on_invalid_stt_model(self):
        """Invalid STT model name produces a warning."""
        cfg = {**DEFAULT_CONFIG, "local_stt_model": "huge"}
        warnings = validate_config(cfg)
        assert any("local_stt_model" in w for w in warnings)

    def test_accepts_valid_stt_models(self):
        """All VALID_STT_MODELS pass without warnings."""
        for model in VALID_STT_MODELS:
            cfg = {**DEFAULT_CONFIG, "local_stt_model": model}
            warnings = validate_config(cfg)
            assert not any("local_stt_model" in w for w in warnings)

    def test_warns_on_invalid_ollama_url(self):
        """Ollama URL without http/https produces a warning."""
        cfg = {**DEFAULT_CONFIG, "ollama_url": "ftp://localhost:11434"}
        warnings = validate_config(cfg)
        assert any("ollama_url" in w for w in warnings)

    def test_accepts_https_ollama_url(self):
        """HTTPS Ollama URL is valid."""
        cfg = {**DEFAULT_CONFIG, "ollama_url": "https://ollama.example.com"}
        warnings = validate_config(cfg)
        assert not any("ollama_url" in w for w in warnings)

    def test_warns_on_unknown_keys(self):
        """Unknown config keys produce a warning about possible typos."""
        cfg = {**DEFAULT_CONFIG, "use_locl_stt": True, "sampl_rate": 16000}
        warnings = validate_config(cfg)
        assert any("Unknown config keys" in w for w in warnings)
        assert any("sampl_rate" in w for w in warnings)
        assert any("use_locl_stt" in w for w in warnings)

    def test_multiple_issues_produce_multiple_warnings(self):
        """Config with multiple issues returns multiple warnings."""
        cfg = {
            **DEFAULT_CONFIG,
            "tts_speed": 10.0,
            "sample_rate": 1,
            "use_local_stt": "yes",
            "local_stt_model": "huge",
        }
        warnings = validate_config(cfg)
        assert len(warnings) >= 4

    def test_load_config_logs_warnings(self, monkeypatch, tmp_path, caplog):
        """load_config logs validation warnings for bad user config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"tts_speed": 999.0}))
        monkeypatch.setattr(config, "CONFIG_PATH", config_file)

        import logging

        with caplog.at_level(logging.WARNING, logger="synthia.config"):
            load_config()

        assert any("tts_speed" in record.message for record in caplog.records)
