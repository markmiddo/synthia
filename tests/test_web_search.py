"""Tests for synthia.web_search module."""

from __future__ import annotations

import pytest

from synthia import web_search as ws_module
from synthia.web_search import WebSearch, web_search


class TestWebSearchInit:
    """Tests for WebSearch.__init__."""

    def test_stores_api_key_and_creates_client(self, mocker):
        """WebSearch stores the API key by creating a TavilyClient."""
        mock_client_cls = mocker.patch("synthia.web_search.TavilyClient")

        searcher = WebSearch(api_key="tvly-test-key-123")

        mock_client_cls.assert_called_once_with(api_key="tvly-test-key-123")
        assert searcher.client is mock_client_cls.return_value

    def test_loads_api_key_from_config_when_not_provided(self, mocker):
        """WebSearch loads api_key from config when none is passed."""
        mocker.patch(
            "synthia.web_search.load_config",
            return_value={"tavily_api_key": "tvly-from-config"},
        )
        mock_client_cls = mocker.patch("synthia.web_search.TavilyClient")

        searcher = WebSearch()

        mock_client_cls.assert_called_once_with(api_key="tvly-from-config")
        assert searcher.client is mock_client_cls.return_value

    def test_raises_value_error_when_no_api_key(self, mocker):
        """WebSearch raises ValueError when no API key is available."""
        mocker.patch(
            "synthia.web_search.load_config",
            return_value={"tavily_api_key": ""},
        )
        mocker.patch("synthia.web_search.TavilyClient")

        with pytest.raises(ValueError, match="Tavily API key not configured"):
            WebSearch()

    def test_raises_value_error_when_config_has_no_key(self, mocker):
        """WebSearch raises ValueError when config dict lacks tavily_api_key entirely."""
        mocker.patch(
            "synthia.web_search.load_config",
            return_value={},
        )
        mocker.patch("synthia.web_search.TavilyClient")

        with pytest.raises(ValueError, match="Tavily API key not configured"):
            WebSearch()

    def test_raises_when_explicit_empty_string(self, mocker):
        """WebSearch raises ValueError when explicitly passed an empty string."""
        mocker.patch("synthia.web_search.TavilyClient")

        with pytest.raises(ValueError, match="Tavily API key not configured"):
            WebSearch(api_key="")


class TestSearch:
    """Tests for WebSearch.search method."""

    @pytest.fixture
    def searcher(self, mocker):
        """Create a WebSearch instance with a mocked TavilyClient."""
        mocker.patch("synthia.web_search.TavilyClient")
        return WebSearch(api_key="tvly-test-key")

    def test_returns_results_dict_with_answer_and_sources(self, searcher):
        """search returns dict with answer, sources, and success flag."""
        searcher.client.search.return_value = {
            "answer": "Python is a programming language.",
            "results": [
                {
                    "title": "Python.org",
                    "url": "https://python.org",
                    "content": "Python is a versatile language used worldwide.",
                },
                {
                    "title": "Wikipedia",
                    "url": "https://en.wikipedia.org/wiki/Python",
                    "content": "Python is a high-level programming language.",
                },
            ],
        }

        result = searcher.search("What is Python?")

        assert result["success"] is True
        assert result["answer"] == "Python is a programming language."
        assert len(result["sources"]) == 2
        assert result["sources"][0]["title"] == "Python.org"
        assert result["sources"][0]["url"] == "https://python.org"
        assert result["sources"][0]["snippet"] == "Python is a versatile language used worldwide."

    def test_passes_max_results_to_client(self, searcher):
        """search passes max_results parameter to the Tavily client."""
        searcher.client.search.return_value = {"answer": "", "results": []}

        searcher.search("test query", max_results=5)

        searcher.client.search.assert_called_once_with(
            query="test query",
            search_depth="basic",
            max_results=5,
            include_answer=True,
        )

    def test_truncates_snippet_to_200_chars(self, searcher):
        """search truncates content snippets to 200 characters."""
        long_content = "A" * 500
        searcher.client.search.return_value = {
            "answer": "test",
            "results": [
                {"title": "Test", "url": "https://test.com", "content": long_content},
            ],
        }

        result = searcher.search("test")

        assert len(result["sources"][0]["snippet"]) == 200

    def test_returns_failure_on_client_exception(self, searcher):
        """search returns success=False when the Tavily client raises."""
        searcher.client.search.side_effect = Exception("API rate limit exceeded")

        result = searcher.search("test query")

        assert result["success"] is False
        assert "Search failed" in result["answer"]
        assert "API rate limit exceeded" in result["answer"]
        assert result["sources"] == []

    def test_handles_missing_fields_in_response(self, searcher):
        """search handles results with missing title, url, or content fields."""
        searcher.client.search.return_value = {
            "results": [
                {},  # All fields missing
            ],
        }

        result = searcher.search("test")

        assert result["success"] is True
        assert result["answer"] == ""
        assert len(result["sources"]) == 1
        assert result["sources"][0]["title"] == ""
        assert result["sources"][0]["url"] == ""
        assert result["sources"][0]["snippet"] == ""


class TestQuickAnswer:
    """Tests for WebSearch.quick_answer method."""

    @pytest.fixture
    def searcher(self, mocker):
        """Create a WebSearch instance with a mocked TavilyClient."""
        mocker.patch("synthia.web_search.TavilyClient")
        return WebSearch(api_key="tvly-test-key")

    def test_returns_answer_string_on_success(self, searcher):
        """quick_answer returns the answer string from a successful search."""
        searcher.client.search.return_value = {
            "answer": "The capital of France is Paris.",
            "results": [
                {
                    "title": "France",
                    "url": "https://example.com",
                    "content": "Paris is the capital of France.",
                },
            ],
        }

        result = searcher.quick_answer("What is the capital of France?")

        assert result == "The capital of France is Paris."

    def test_falls_back_to_first_snippet_when_no_answer(self, searcher):
        """quick_answer returns first snippet when answer is empty."""
        searcher.client.search.return_value = {
            "answer": "",
            "results": [
                {
                    "title": "Snippet Source",
                    "url": "https://example.com",
                    "content": "Fallback snippet content here.",
                },
            ],
        }

        result = searcher.quick_answer("obscure question")

        assert result == "Fallback snippet content here."

    def test_returns_fallback_message_when_no_results(self, searcher):
        """quick_answer returns a fallback message when search fails entirely."""
        searcher.client.search.side_effect = Exception("Network error")

        result = searcher.quick_answer("anything")

        assert result == "I couldn't find an answer to that."


class TestWebSearchConvenienceFunction:
    """Tests for the web_search convenience function."""

    def test_returns_answer_string(self, mocker):
        """web_search returns the quick_answer from a successful search."""
        mock_client_cls = mocker.patch("synthia.web_search.TavilyClient")
        mocker.patch(
            "synthia.web_search.load_config",
            return_value={"tavily_api_key": "tvly-test"},
        )
        mock_client_cls.return_value.search.return_value = {
            "answer": "42 is the answer.",
            "results": [],
        }

        result = web_search("meaning of life")

        assert result == "42 is the answer."

    def test_returns_error_string_on_missing_key(self, mocker):
        """web_search returns error message when API key is missing."""
        mocker.patch(
            "synthia.web_search.load_config",
            return_value={"tavily_api_key": ""},
        )
        mocker.patch("synthia.web_search.TavilyClient")

        result = web_search("test")

        assert "Tavily API key not configured" in result

    def test_returns_error_string_on_unexpected_exception(self, mocker):
        """web_search returns error string when an unexpected exception occurs."""
        mocker.patch(
            "synthia.web_search.load_config",
            return_value={"tavily_api_key": "tvly-test"},
        )
        mock_client_cls = mocker.patch("synthia.web_search.TavilyClient")
        mock_client_cls.side_effect = RuntimeError("Unexpected failure")

        result = web_search("test")

        assert "Search error" in result
        assert "Unexpected failure" in result
