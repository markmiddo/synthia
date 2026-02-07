"""Tests for synthia.llm_polish module."""

from __future__ import annotations

import pytest
import requests

from synthia.llm_polish import POLISH_PROMPT, TranscriptionPolisher


class TestTranscriptionPolisherInit:
    """Tests for TranscriptionPolisher.__init__."""

    def test_default_values(self):
        """TranscriptionPolisher uses sensible defaults."""
        polisher = TranscriptionPolisher()

        assert polisher.ollama_url == "http://localhost:11434"
        assert polisher.model == "qwen2.5:7b-instruct-q4_0"
        assert polisher.timeout == 3.0
        assert polisher.enabled is True

    def test_custom_values(self):
        """TranscriptionPolisher accepts custom configuration."""
        polisher = TranscriptionPolisher(
            ollama_url="http://remote:11434",
            model="llama3:8b",
            timeout=5.0,
            enabled=False,
        )

        assert polisher.ollama_url == "http://remote:11434"
        assert polisher.model == "llama3:8b"
        assert polisher.timeout == 5.0
        assert polisher.enabled is False


class TestPolish:
    """Tests for TranscriptionPolisher.polish method."""

    @pytest.fixture
    def polisher(self):
        """Create a TranscriptionPolisher with default settings."""
        return TranscriptionPolisher()

    def test_returns_polished_text_on_success(self, polisher, mocker):
        """polish returns corrected text from the LLM on a successful call."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "I went to the store."}
        mocker.patch("synthia.llm_polish.requests.post", return_value=mock_response)

        result = polisher.polish("I went too the store.")

        assert result == "I went to the store."

    def test_returns_original_text_on_timeout(self, polisher, mocker):
        """polish returns original text when the request times out."""
        mocker.patch(
            "synthia.llm_polish.requests.post",
            side_effect=requests.exceptions.Timeout("Connection timed out"),
        )

        result = polisher.polish("hello their world")

        assert result == "hello their world"

    def test_returns_original_text_on_connection_error(self, polisher, mocker):
        """polish returns original text when a connection error occurs."""
        mocker.patch(
            "synthia.llm_polish.requests.post",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        result = polisher.polish("the python language")

        assert result == "the python language"

    def test_returns_original_text_on_bad_status_code(self, polisher, mocker):
        """polish returns original text when server returns 500."""
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mocker.patch("synthia.llm_polish.requests.post", return_value=mock_response)

        result = polisher.polish("some transcription text")

        assert result == "some transcription text"

    def test_returns_original_when_disabled(self, mocker):
        """polish returns original text without calling LLM when disabled."""
        mock_post = mocker.patch("synthia.llm_polish.requests.post")
        polisher = TranscriptionPolisher(enabled=False)

        result = polisher.polish("hello world")

        assert result == "hello world"
        mock_post.assert_not_called()

    def test_returns_original_for_empty_input(self, polisher, mocker):
        """polish returns original text for whitespace-only input."""
        mock_post = mocker.patch("synthia.llm_polish.requests.post")

        result = polisher.polish("   ")

        assert result == "   "
        mock_post.assert_not_called()

    def test_returns_original_when_llm_returns_empty(self, polisher, mocker):
        """polish returns original text when LLM returns empty response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": ""}
        mocker.patch("synthia.llm_polish.requests.post", return_value=mock_response)

        result = polisher.polish("some text here")

        assert result == "some text here"

    def test_returns_original_when_llm_output_too_long(self, polisher, mocker):
        """polish returns original when LLM output exceeds 2x the input length."""
        original = "short text"
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        # Return something > 2x original length
        mock_response.json.return_value = {"response": "A" * (len(original) * 2 + 1)}
        mocker.patch("synthia.llm_polish.requests.post", return_value=mock_response)

        result = polisher.polish(original)

        assert result == original


class TestPolishPromptContent:
    """Tests for the POLISH_PROMPT template."""

    def test_prompt_includes_transcription_placeholder(self):
        """POLISH_PROMPT contains a {transcription} placeholder."""
        assert "{transcription}" in POLISH_PROMPT

    def test_prompt_includes_original_text_when_formatted(self):
        """Formatted prompt includes the original transcription text."""
        original_text = "I went too the store and bought sum apples."
        formatted = POLISH_PROMPT.format(transcription=original_text)

        assert original_text in formatted


class TestPolishRequestPayload:
    """Tests verifying the request payload sent to Ollama."""

    def test_request_includes_correct_url_and_payload(self, mocker):
        """polish sends correct URL, model, prompt, and options to Ollama."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "corrected text"}
        mock_post = mocker.patch("synthia.llm_polish.requests.post", return_value=mock_response)

        polisher = TranscriptionPolisher(
            ollama_url="http://localhost:11434",
            model="qwen2.5:7b-instruct-q4_0",
            timeout=3.0,
        )
        polisher.polish("original text here")

        mock_post.assert_called_once()
        call_args = mock_post.call_args

        # Verify URL
        assert call_args[0][0] == "http://localhost:11434/api/generate"

        # Verify JSON payload
        payload = call_args[1]["json"]
        assert payload["model"] == "qwen2.5:7b-instruct-q4_0"
        assert "original text here" in payload["prompt"]
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.1
        assert payload["options"]["num_predict"] == len("original text here") + 50
        assert payload["options"]["top_p"] == 0.9

        # Verify timeout
        assert call_args[1]["timeout"] == 3.0
