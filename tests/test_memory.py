"""Tests for the MemorySystem class in src/synthia/memory.py."""

import json
from pathlib import Path

import pytest

from synthia.memory import MEMORY_CATEGORIES, MemoryEntry, MemorySystem


class TestRemember:
    """Tests for the remember method."""

    def test_remember_stores_bug_entry_to_bugs_jsonl(self, tmp_memory_dir: Path):
        """Remember stores bug entry to bugs.jsonl with correct structure."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        result = memory.remember(
            category="bug",
            tags=["python", "import"],
            error="ModuleNotFoundError",
            cause="Missing dependency",
            fix="pip install package",
        )

        assert result is True
        bugs_file = tmp_memory_dir / "bugs.jsonl"
        assert bugs_file.exists()

        with open(bugs_file) as f:
            entry = json.loads(f.readline())

        assert entry["error"] == "ModuleNotFoundError"
        assert entry["cause"] == "Missing dependency"
        assert entry["fix"] == "pip install package"
        assert "python" in entry["tags"]
        assert "import" in entry["tags"]
        assert "date" in entry

    def test_remember_stores_pattern_entry_to_patterns_jsonl(self, tmp_memory_dir: Path):
        """Remember stores pattern entry to patterns.jsonl."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        result = memory.remember(
            category="pattern",
            tags=["testing", "pytest"],
            topic="Fixture usage",
            rule="Use fixtures for setup",
            why="Cleaner test code",
        )

        assert result is True
        patterns_file = tmp_memory_dir / "patterns.jsonl"
        assert patterns_file.exists()

        with open(patterns_file) as f:
            entry = json.loads(f.readline())

        assert entry["topic"] == "Fixture usage"
        assert entry["rule"] == "Use fixtures for setup"
        assert entry["why"] == "Cleaner test code"

    def test_remember_rejects_invalid_category(self, tmp_memory_dir: Path):
        """Remember returns False for invalid category."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        result = memory.remember(
            category="invalid_category",
            tags=["test"],
            some_field="value",
        )

        assert result is False

    def test_remember_rejects_missing_required_fields(self, tmp_memory_dir: Path):
        """Remember returns False when required fields are missing."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        # Bug category requires error, cause, fix
        result = memory.remember(
            category="bug",
            tags=["test"],
            error="Some error",
            # missing cause and fix
        )

        assert result is False


class TestRecall:
    """Tests for the recall method."""

    def test_recall_finds_entries_by_matching_tag(self, tmp_memory_dir: Path):
        """Recall finds entries that match a given tag."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(
            category="bug",
            tags=["python", "import"],
            error="ImportError",
            cause="Wrong path",
            fix="Fix import path",
        )
        memory.remember(
            category="bug",
            tags=["javascript", "npm"],
            error="Module not found",
            cause="Not installed",
            fix="npm install",
        )

        results = memory.recall(tags=["python"])

        assert len(results) == 1
        assert results[0].data["error"] == "ImportError"

    def test_recall_with_multiple_tags_uses_or_logic(self, tmp_memory_dir: Path):
        """Recall with multiple tags returns entries matching ANY tag (OR logic)."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(
            category="bug",
            tags=["python"],
            error="Error 1",
            cause="Cause 1",
            fix="Fix 1",
        )
        memory.remember(
            category="bug",
            tags=["javascript"],
            error="Error 2",
            cause="Cause 2",
            fix="Fix 2",
        )
        memory.remember(
            category="bug",
            tags=["rust"],
            error="Error 3",
            cause="Cause 3",
            fix="Fix 3",
        )

        results = memory.recall(tags=["python", "javascript"])

        assert len(results) == 2
        errors = [r.data["error"] for r in results]
        assert "Error 1" in errors
        assert "Error 2" in errors

    def test_recall_respects_category_filter(self, tmp_memory_dir: Path):
        """Recall only returns entries from specified category."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(
            category="bug",
            tags=["python"],
            error="Bug error",
            cause="Bug cause",
            fix="Bug fix",
        )
        memory.remember(
            category="pattern",
            tags=["python"],
            topic="Pattern topic",
            rule="Pattern rule",
            why="Pattern why",
        )

        results = memory.recall(tags=["python"], category="bug")

        assert len(results) == 1
        assert results[0].category == "bug"
        assert results[0].data["error"] == "Bug error"

    def test_recall_respects_limit_parameter(self, tmp_memory_dir: Path):
        """Recall returns at most 'limit' entries."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        for i in range(5):
            memory.remember(
                category="bug",
                tags=["test"],
                error=f"Error {i}",
                cause=f"Cause {i}",
                fix=f"Fix {i}",
            )

        results = memory.recall(tags=["test"], limit=3)

        assert len(results) == 3

    def test_recall_returns_empty_for_no_matches(self, tmp_memory_dir: Path):
        """Recall returns empty list when no entries match."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(
            category="bug",
            tags=["python"],
            error="Error",
            cause="Cause",
            fix="Fix",
        )

        results = memory.recall(tags=["nonexistent_tag"])

        assert results == []


class TestSearchText:
    """Tests for the search_text method."""

    def test_search_text_finds_entries_by_content_case_insensitive(self, tmp_memory_dir: Path):
        """Search text finds entries matching query (case insensitive)."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(
            category="bug",
            tags=["python"],
            error="ModuleNotFoundError",
            cause="Package missing",
            fix="Install the package",
        )

        results = memory.search_text("MODULENOTFOUNDERROR")

        assert len(results) == 1
        assert results[0].data["error"] == "ModuleNotFoundError"

    def test_search_text_returns_empty_for_no_matches(self, tmp_memory_dir: Path):
        """Search text returns empty list when no entries match."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(
            category="bug",
            tags=["python"],
            error="Some error",
            cause="Some cause",
            fix="Some fix",
        )

        results = memory.search_text("completely_unrelated_query")

        assert results == []


class TestListCategories:
    """Tests for the list_categories method."""

    def test_list_categories_returns_correct_counts(self, tmp_memory_dir: Path):
        """List categories returns dict of category to entry count."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(category="bug", tags=["t1"], error="E1", cause="C1", fix="F1")
        memory.remember(category="bug", tags=["t2"], error="E2", cause="C2", fix="F2")
        memory.remember(category="pattern", tags=["t3"], topic="T1", rule="R1", why="W1")

        counts = memory.list_categories()

        assert counts.get("bug") == 2
        assert counts.get("pattern") == 1


class TestListAllTags:
    """Tests for the list_all_tags method."""

    def test_list_all_tags_returns_sorted_tag_counts(self, tmp_memory_dir: Path):
        """List all tags returns dict of tag to count, sorted by count descending."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)
        memory.remember(category="bug", tags=["python", "import"], error="E1", cause="C1", fix="F1")
        memory.remember(category="bug", tags=["python", "async"], error="E2", cause="C2", fix="F2")
        memory.remember(category="bug", tags=["python"], error="E3", cause="C3", fix="F3")

        tags = memory.list_all_tags()

        # Python should appear 3 times, import and async once each
        assert tags["python"] == 3
        assert tags["import"] == 1
        assert tags["async"] == 1

        # Check sorting - python should be first
        tag_list = list(tags.keys())
        assert tag_list[0] == "python"


class TestMemoryEntry:
    """Tests for the MemoryEntry dataclass."""

    def test_to_dict_includes_tags_and_date(self):
        """MemoryEntry.to_dict includes tags and date fields."""
        entry = MemoryEntry(
            category="bug",
            data={"error": "TestError", "cause": "TestCause", "fix": "TestFix"},
            tags=["python", "testing"],
            date="2024-01-15",
        )

        result = entry.to_dict()

        assert result["tags"] == ["python", "testing"]
        assert result["date"] == "2024-01-15"
        assert result["error"] == "TestError"
        assert result["cause"] == "TestCause"
        assert result["fix"] == "TestFix"

    def test_from_dict_creates_correct_entry(self):
        """MemoryEntry.from_dict creates entry with correct fields."""
        data = {
            "error": "TestError",
            "cause": "TestCause",
            "fix": "TestFix",
            "tags": ["python", "testing"],
            "date": "2024-01-15",
        }

        entry = MemoryEntry.from_dict("bug", data)

        assert entry.category == "bug"
        assert entry.data["error"] == "TestError"
        assert entry.data["cause"] == "TestCause"
        assert entry.data["fix"] == "TestFix"
        assert entry.tags == ["python", "testing"]
        assert entry.date == "2024-01-15"

    def test_format_display_for_bug_category(self):
        """MemoryEntry.format_display produces readable output for bug category."""
        entry = MemoryEntry(
            category="bug",
            data={"error": "ImportError", "cause": "Missing module", "fix": "pip install module"},
            tags=["python", "import"],
            date="2024-01-15",
        )

        display = entry.format_display()

        assert "ImportError" in display
        assert "Missing module" in display
        assert "pip install module" in display


class TestEnsureMemoryDir:
    """Tests for the _ensure_memory_dir method."""

    def test_ensure_memory_dir_creates_files_if_missing(self, tmp_path: Path):
        """_ensure_memory_dir creates memory directory and JSONL files if they don't exist."""
        memory_dir = tmp_path / "new_memory_dir"
        assert not memory_dir.exists()

        memory = MemorySystem(memory_dir=memory_dir)

        assert memory_dir.exists()
        for category, filename in MEMORY_CATEGORIES.items():
            file_path = memory_dir / filename
            assert file_path.exists(), f"Expected {filename} to be created"


class TestGetContextForTask:
    """Tests for get_context_for_task method."""

    def test_get_context_returns_matching_memories(self, tmp_memory_dir: Path):
        """Get context for task returns memories with matching keywords."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        # Add a memory with 'react' keyword
        memory.remember(
            category="pattern",
            tags=["react", "hooks"],
            topic="React hooks",
            rule="Use hooks for state",
            why="Better composability",
        )

        # Task description containing 'react' should find this
        context = memory.get_context_for_task("I need to implement a React component")

        assert context != ""
        assert "React hooks" in context

    def test_get_context_returns_empty_for_no_matches(self, tmp_memory_dir: Path):
        """Get context returns empty string when no keywords match."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        memory.remember(
            category="bug",
            tags=["python"],
            error="Import error",
            cause="Missing module",
            fix="Install it",
        )

        # Task with no matching keywords
        context = memory.get_context_for_task("Write documentation for the API")

        assert context == ""

    def test_get_context_finds_multiple_memories(self, tmp_memory_dir: Path):
        """Get context can return multiple matching memories."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        memory.remember(
            category="gotcha",
            tags=["typescript", "types"],
            area="Type checking",
            gotcha="String literals matter for types",
        )

        memory.remember(
            category="stack",
            tags=["typescript", "compiler"],
            tool="TypeScript",
            note="Enable strict mode in tsconfig",
        )

        context = memory.get_context_for_task("Fixing TypeScript type errors in the new module")

        assert context != ""
        assert "Type checking" in context or "TypeScript" in context


class TestExtractKeywords:
    """Tests for _extract_keywords method."""

    def test_extract_keywords_finds_known_tags(self, tmp_memory_dir: Path):
        """Extract keywords finds known tags in text."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        keywords = memory._extract_keywords("Building a React app with TypeScript")

        assert "react" in keywords
        assert "typescript" in keywords

    def test_extract_keywords_is_case_insensitive(self, tmp_memory_dir: Path):
        """Extract keywords is case insensitive."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        keywords = memory._extract_keywords("Using REACT and TypeScript")

        assert "react" in keywords
        assert "typescript" in keywords

    def test_extract_keywords_returns_empty_for_unrelated_text(self, tmp_memory_dir: Path):
        """Extract keywords returns empty for completely unrelated text."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        keywords = memory._extract_keywords("The quick brown fox jumps")

        assert keywords == []

    def test_extract_keywords_finds_backend_keywords(self, tmp_memory_dir: Path):
        """Extract keywords finds backend-related keywords."""
        memory = MemorySystem(memory_dir=tmp_memory_dir)

        keywords = memory._extract_keywords("Implementing Go API with MongoDB")

        assert "go" in keywords
        assert "mongodb" in keywords
        assert "api" in keywords


class TestMemoryEntryFormatDisplay:
    """Tests for MemoryEntry.format_display for different categories."""

    def test_format_display_for_pattern_category(self):
        """Format display produces readable output for pattern category."""
        entry = MemoryEntry(
            category="pattern",
            data={"topic": "Error handling", "rule": "Use try/catch blocks", "why": "Safety"},
            tags=["javascript"],
            date="2024-01-15",
        )

        display = entry.format_display()

        assert "[PATTERN]" in display
        assert "Error handling" in display
        assert "Use try/catch blocks" in display
        assert "Safety" in display

    def test_format_display_for_arch_category(self):
        """Format display produces readable output for arch category."""
        entry = MemoryEntry(
            category="arch",
            data={"decision": "Monorepo structure", "why": "Easier sharing of code"},
            tags=["architecture"],
            date="2024-01-15",
        )

        display = entry.format_display()

        assert "[ARCHITECTURE]" in display
        assert "Monorepo structure" in display
        assert "Easier sharing of code" in display

    def test_format_display_for_gotcha_category(self):
        """Format display produces readable output for gotcha category."""
        entry = MemoryEntry(
            category="gotcha",
            data={"area": "Async operations", "gotcha": "Don't forget to await promises"},
            tags=["javascript"],
            date="2024-01-15",
        )

        display = entry.format_display()

        assert "[GOTCHA]" in display
        assert "Async operations" in display
        assert "Don't forget to await promises" in display

    def test_format_display_for_stack_category(self):
        """Format display produces readable output for stack category."""
        entry = MemoryEntry(
            category="stack",
            data={"tool": "Docker", "note": "Always use .dockerignore file"},
            tags=["devops"],
            date="2024-01-15",
        )

        display = entry.format_display()

        assert "[STACK]" in display
        assert "Docker" in display
        assert "Always use .dockerignore file" in display

    def test_format_display_includes_tags(self):
        """Format display always includes tags."""
        entry = MemoryEntry(
            category="bug",
            data={"error": "Error", "cause": "Cause", "fix": "Fix"},
            tags=["tag1", "tag2", "tag3"],
            date="2024-01-15",
        )

        display = entry.format_display()

        assert "tag1" in display
        assert "tag2" in display
        assert "tag3" in display


class TestConvenienceFunctions:
    """Tests for convenience functions recall(), remember(), search()."""

    def test_recall_convenience_function(self, tmp_memory_dir: Path, monkeypatch):
        """recall() convenience function delegates to singleton."""
        # Reset singleton
        import synthia.memory
        from synthia.memory import _memory_system, recall, remember

        synthia.memory._memory_system = None

        monkeypatch.setattr("synthia.memory.DEFAULT_MEMORY_DIR", tmp_memory_dir)

        # Add a memory
        remember(
            category="bug",
            tags=["python", "test"],
            error="Error",
            cause="Cause",
            fix="Fix",
        )

        # Recall it
        results = recall(tags=["python"])

        assert len(results) == 1
        assert results[0].data["error"] == "Error"

    def test_remember_convenience_function(self, tmp_memory_dir: Path, monkeypatch):
        """remember() convenience function delegates to singleton."""
        # Reset singleton
        import synthia.memory
        from synthia.memory import _memory_system, remember

        synthia.memory._memory_system = None

        monkeypatch.setattr("synthia.memory.DEFAULT_MEMORY_DIR", tmp_memory_dir)

        result = remember(
            category="pattern",
            tags=["testing"],
            topic="Test fixtures",
            rule="Use fixtures",
            why="Cleaner",
        )

        assert result is True

    def test_search_convenience_function(self, tmp_memory_dir: Path, monkeypatch):
        """search() convenience function delegates to singleton."""
        # Reset singleton
        import synthia.memory
        from synthia.memory import remember, search

        synthia.memory._memory_system = None

        monkeypatch.setattr("synthia.memory.DEFAULT_MEMORY_DIR", tmp_memory_dir)

        # Add a memory
        remember(
            category="bug",
            tags=["test"],
            error="ModuleNotFoundError",
            cause="Missing",
            fix="Install",
        )

        # Search for it
        results = search("ModuleNotFoundError")

        assert len(results) == 1
        assert results[0].data["error"] == "ModuleNotFoundError"
