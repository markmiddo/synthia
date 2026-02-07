"""Tests for synthia.assistant module."""

import json
from unittest.mock import MagicMock

import pytest

from synthia.assistant import SYSTEM_PROMPT, Assistant


class TestAssistantInit:
    """Test Assistant __init__ stores config correctly."""

    def test_init_local_mode(self):
        """Local mode sets use_local=True and uses the local model name."""
        assistant = Assistant(use_local=True, local_model="llama3:8b")
        assert assistant.use_local is True
        assert assistant.model == "llama3:8b"
        assert assistant.client is None
        assert assistant.conversation_history == []
        assert assistant.memory_size == 10

    def test_init_local_mode_defaults(self):
        """Local mode with default local_model."""
        assistant = Assistant(use_local=True)
        assert assistant.model == "qwen2.5:7b-instruct-q4_0"
        assert assistant.ollama_url == "http://localhost:11434"

    def test_init_claude_mode(self, mocker):
        """Claude mode creates an Anthropic client."""
        mock_anthropic_cls = MagicMock()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mocker.patch.dict("sys.modules", {"anthropic": mock_anthropic_cls})
        mock_anthropic_cls.Anthropic = MagicMock(return_value=mock_client)

        # Re-import to pick up the mock -- but the import happens inside __init__
        # so we need to patch it at that level
        mocker.patch("anthropic.Anthropic", mock_anthropic_cls.Anthropic, create=True)

        assistant = Assistant(api_key="test-key", use_local=False)
        assert assistant.use_local is False
        assert assistant.model == "claude-haiku-4-20250514"
        assert assistant.client is not None

    def test_init_custom_memory_size(self):
        """Memory size is configurable."""
        assistant = Assistant(use_local=True, memory_size=5)
        assert assistant.memory_size == 5

    def test_init_custom_ollama_url(self):
        """Ollama URL is configurable."""
        assistant = Assistant(use_local=True, ollama_url="http://192.168.1.10:11434")
        assert assistant.ollama_url == "http://192.168.1.10:11434"

    def test_init_dev_mode(self):
        """Dev mode flag is stored."""
        assistant = Assistant(use_local=True, dev_mode=True)
        assert assistant.dev_mode is True

    def test_init_dev_mode_default_false(self):
        """Dev mode defaults to False."""
        assistant = Assistant(use_local=True)
        assert assistant.dev_mode is False


class TestAddToHistory:
    """Test conversation history management."""

    def test_add_to_history_basic(self):
        """Messages are appended to history."""
        assistant = Assistant(use_local=True, memory_size=10)
        assistant._add_to_history("user", "Hello")
        assert len(assistant.conversation_history) == 1
        assert assistant.conversation_history[0] == {"role": "user", "content": "Hello"}

    def test_add_to_history_multiple(self):
        """Multiple messages are stored in order."""
        assistant = Assistant(use_local=True, memory_size=10)
        assistant._add_to_history("user", "Hello")
        assistant._add_to_history("assistant", '{"speech": "Hi!", "actions": []}')
        assert len(assistant.conversation_history) == 2
        assert assistant.conversation_history[0]["role"] == "user"
        assert assistant.conversation_history[1]["role"] == "assistant"

    def test_history_trimming(self):
        """History is trimmed when it exceeds memory_size * 2."""
        assistant = Assistant(use_local=True, memory_size=2)
        # memory_size=2 means max 4 messages (2 pairs)
        for i in range(6):
            assistant._add_to_history("user", f"msg-{i}")
        # After 6 additions with limit of 4, should have trimmed down to 4
        assert len(assistant.conversation_history) == 4
        # Oldest messages should have been removed
        assert assistant.conversation_history[0]["content"] == "msg-2"
        assert assistant.conversation_history[-1]["content"] == "msg-5"


class TestParseResponse:
    """Test _parse_response JSON parsing logic."""

    def setup_method(self):
        """Create a local assistant for parse testing."""
        self.assistant = Assistant(use_local=True, memory_size=10)

    def test_parse_valid_json(self):
        """Valid JSON with speech and actions is parsed correctly."""
        response = '{"speech": "Hello there.", "actions": []}'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Hello there."
        assert result["actions"] == []

    def test_parse_json_with_actions(self):
        """JSON with actions is parsed correctly."""
        response = json.dumps(
            {
                "speech": "Turning up the volume.",
                "actions": [{"type": "change_volume", "delta": 10}],
            }
        )
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Turning up the volume."
        assert len(result["actions"]) == 1
        assert result["actions"][0]["type"] == "change_volume"
        assert result["actions"][0]["delta"] == 10

    def test_parse_markdown_code_block(self):
        """JSON wrapped in markdown code blocks is extracted."""
        response = '```json\n{"speech": "Done.", "actions": []}\n```'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Done."
        assert result["actions"] == []

    def test_parse_markdown_code_block_no_language(self):
        """JSON wrapped in plain markdown code blocks is extracted."""
        response = '```\n{"speech": "Done.", "actions": []}\n```'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Done."
        assert result["actions"] == []

    def test_parse_missing_speech_key(self):
        """Missing speech key gets a default value."""
        response = '{"actions": [{"type": "mute"}]}'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "I processed your request."
        assert len(result["actions"]) == 1

    def test_parse_missing_actions_key(self):
        """Missing actions key gets a default empty list."""
        response = '{"speech": "Hello!"}'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Hello!"
        assert result["actions"] == []

    def test_parse_invalid_json_fallback(self):
        """Invalid JSON falls back to treating the text as speech."""
        response = "I don't know how to respond in JSON."
        result = self.assistant._parse_response(response)
        assert "I don't know how to respond in JSON." in result["speech"]
        assert result["actions"] == []

    def test_parse_trailing_comma_fix(self):
        """Trailing commas before } are fixed."""
        response = '{"speech": "Hi.",  "actions": [],}'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Hi."

    def test_parse_json_embedded_in_text(self):
        """JSON embedded within surrounding text is extracted via bracket matching."""
        response = 'Here is my response: {"speech": "Got it.", "actions": []} Hope that helps!'
        result = self.assistant._parse_response(response)
        assert result["speech"] == "Got it."
        assert result["actions"] == []

    def test_parse_adds_to_history(self):
        """Parsed response is added to conversation history."""
        response = '{"speech": "Hello!", "actions": []}'
        self.assistant._parse_response(response)
        assert len(self.assistant.conversation_history) == 1
        assert self.assistant.conversation_history[0]["role"] == "assistant"

    def test_parse_complex_actions(self):
        """Multiple actions are parsed correctly."""
        response = json.dumps(
            {
                "speech": "Opening Firefox and maximizing.",
                "actions": [
                    {"type": "open_app", "app": "firefox"},
                    {"type": "maximize_window"},
                ],
            }
        )
        result = self.assistant._parse_response(response)
        assert len(result["actions"]) == 2
        assert result["actions"][0]["type"] == "open_app"
        assert result["actions"][1]["type"] == "maximize_window"


class TestProcess:
    """Test the main process() method."""

    def test_process_empty_input(self):
        """Empty input returns a default message without calling any API."""
        assistant = Assistant(use_local=True)
        result = assistant.process("")
        assert result["speech"] == "I didn't catch that. Could you repeat?"
        assert result["actions"] == []

    def test_process_whitespace_only_input(self):
        """Whitespace-only input returns the default message."""
        assistant = Assistant(use_local=True)
        result = assistant.process("   \n\t  ")
        assert result["speech"] == "I didn't catch that. Could you repeat?"
        assert result["actions"] == []

    def test_process_local_calls_ollama(self, mocker):
        """Process with use_local=True calls _process_ollama."""
        assistant = Assistant(use_local=True)
        mock_ollama = mocker.patch.object(
            assistant,
            "_process_ollama",
            return_value={"speech": "Hi!", "actions": []},
        )
        result = assistant.process("Hello")
        mock_ollama.assert_called_once_with("Hello")
        assert result["speech"] == "Hi!"

    def test_process_claude_calls_claude(self, mocker):
        """Process with use_local=False calls _process_claude."""
        assistant = Assistant(use_local=True)
        assistant.use_local = False  # Override to avoid needing Anthropic import
        mock_claude = mocker.patch.object(
            assistant,
            "_process_claude",
            return_value={"speech": "Hi from Claude!", "actions": []},
        )
        result = assistant.process("Hello")
        mock_claude.assert_called_once_with("Hello")
        assert result["speech"] == "Hi from Claude!"

    def test_process_exception_returns_error(self, mocker):
        """Exceptions during processing return an error message."""
        assistant = Assistant(use_local=True)
        mocker.patch.object(
            assistant,
            "_process_ollama",
            side_effect=Exception("Connection refused"),
        )
        result = assistant.process("Hello")
        assert "error" in result["speech"].lower()
        assert "Connection refused" in result["speech"]
        assert result["actions"] == []

    def test_process_adds_user_to_history(self, mocker):
        """User input is added to history before processing."""
        assistant = Assistant(use_local=True)
        mocker.patch.object(
            assistant,
            "_process_ollama",
            return_value={"speech": "Hi!", "actions": []},
        )
        assistant.process("Hello there")
        # History should have the user message (added by process)
        # and the assistant response (added by _parse_response, but we mocked _process_ollama)
        assert any(
            msg["role"] == "user" and msg["content"] == "Hello there"
            for msg in assistant.conversation_history
        )

    def test_process_dev_mode_enriches_input(self, mocker):
        """In dev mode, memory context is prepended to user input."""
        assistant = Assistant(use_local=True, dev_mode=True)
        mocker.patch.object(
            assistant,
            "_get_memory_context",
            return_value="[Memory: React patterns]",
        )
        mock_ollama = mocker.patch.object(
            assistant,
            "_process_ollama",
            return_value={"speech": "Done.", "actions": []},
        )
        assistant.process("Tell me about React")
        # The enriched input should contain memory context + user request
        call_arg = mock_ollama.call_args[0][0]
        assert "[Memory: React patterns]" in call_arg
        assert "Tell me about React" in call_arg

    def test_process_dev_mode_no_memory_context(self, mocker):
        """In dev mode with empty memory context, input is not enriched."""
        assistant = Assistant(use_local=True, dev_mode=True)
        mocker.patch.object(
            assistant,
            "_get_memory_context",
            return_value="",
        )
        mock_ollama = mocker.patch.object(
            assistant,
            "_process_ollama",
            return_value={"speech": "Done.", "actions": []},
        )
        assistant.process("Hello")
        call_arg = mock_ollama.call_args[0][0]
        assert call_arg == "Hello"


class TestClearHistory:
    """Test clearing conversation history."""

    def test_clear_history(self):
        """Clear history empties the list."""
        assistant = Assistant(use_local=True)
        assistant._add_to_history("user", "Hello")
        assistant._add_to_history("assistant", "Hi!")
        assert len(assistant.conversation_history) == 2
        assistant.clear_history()
        assert assistant.conversation_history == []


class TestProcessOllama:
    """Test _process_ollama makes correct HTTP requests."""

    def test_process_ollama_success(self, mocker):
        """Successful Ollama API call returns parsed response."""
        assistant = Assistant(use_local=True, local_model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": '{"speech": "Hello!", "actions": []}'}
        }
        mocker.patch("synthia.assistant.requests.post", return_value=mock_response)

        result = assistant._process_ollama("Hi")
        assert result["speech"] == "Hello!"
        assert result["actions"] == []

    def test_process_ollama_error_status(self, mocker):
        """Non-200 status from Ollama raises an exception."""
        assistant = Assistant(use_local=True)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mocker.patch("synthia.assistant.requests.post", return_value=mock_response)

        with pytest.raises(Exception, match="Ollama error: 500"):
            assistant._process_ollama("Hi")

    def test_process_ollama_sends_correct_payload(self, mocker):
        """Ollama API call includes system prompt, conversation, and model config."""
        assistant = Assistant(
            use_local=True,
            local_model="test-model",
            ollama_url="http://myhost:11434",
        )
        assistant._add_to_history("user", "Previous message")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": '{"speech": "OK", "actions": []}'}
        }
        mock_post = mocker.patch("synthia.assistant.requests.post", return_value=mock_response)

        assistant._process_ollama("New message")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://myhost:11434/api/chat"
        payload = call_args[1]["json"]
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert payload["messages"][0]["role"] == "system"
        assert len(payload["messages"]) >= 2  # system + at least one history entry


class TestSystemPrompt:
    """Test SYSTEM_PROMPT template."""

    def test_system_prompt_has_date_placeholder(self):
        """SYSTEM_PROMPT contains {date} placeholder for formatting."""
        assert "{date}" in SYSTEM_PROMPT

    def test_system_prompt_formats_correctly(self):
        """SYSTEM_PROMPT can be formatted with a date string."""
        formatted = SYSTEM_PROMPT.format(date="Monday, January 01, 2025 at 10:00 AM")
        assert "Monday, January 01, 2025 at 10:00 AM" in formatted
        assert "{date}" not in formatted
