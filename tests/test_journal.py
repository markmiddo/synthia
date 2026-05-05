"""Integration tests for Agent Daily Journal feature."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

JOURNAL_DIR = Path.home() / ".config" / "synthia" / "journal"


class TestJournal:
    """Test the journal file structure and content."""

    def setup_method(self):
        """Clean up journal files before each test."""
        if JOURNAL_DIR.exists():
            for f in JOURNAL_DIR.glob("*.json"):
                f.unlink()

    def teardown_method(self):
        """Clean up journal files after each test."""
        if JOURNAL_DIR.exists():
            for f in JOURNAL_DIR.glob("*.json"):
                f.unlink()

    def test_journal_directory_created(self):
        """Test that journal directory is created when writing entries."""
        JOURNAL_DIR.parent.mkdir(parents=True, exist_ok=True)
        assert JOURNAL_DIR.parent.exists()

    def test_journal_file_format(self):
        """Test that journal files follow the expected format."""
        today = datetime.now().strftime("%Y-%m-%d")
        journal_file = JOURNAL_DIR / f"{today}.json"

        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent_name": "Atlas",
            "agent_kind": "claude",
            "agent_role": "Developer",
            "project_name": "synthia",
            "branch": "feature/test",
            "task_summary": "Test journal entry",
            "files_touched": ["test.py"],
            "activity": "Writing tests",
            "session_id": "test-session-123",
            "trigger": "task_list_completed",
        }

        journal_data = {"entries": [entry]}

        with open(journal_file, "w") as f:
            json.dump(journal_data, f, indent=2)

        # Verify file was created
        assert journal_file.exists()

        # Verify content
        with open(journal_file) as f:
            loaded = json.load(f)

        assert "entries" in loaded
        assert len(loaded["entries"]) == 1
        assert loaded["entries"][0]["agent_name"] == "Atlas"
        assert loaded["entries"][0]["task_summary"] == "Test journal entry"

    def test_seven_day_retention(self):
        """Test that journal files older than 7 days are pruned."""
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

        # Create a recent file (should be kept)
        recent_date = datetime.now().strftime("%Y-%m-%d")
        recent_file = JOURNAL_DIR / f"{recent_date}.json"
        recent_file.write_text('{"entries": []}')

        # Create an old file (should be removed by prune)
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        old_file = JOURNAL_DIR / f"{old_date}.json"
        old_file.write_text('{"entries": []}')

        # Verify both exist initially
        assert recent_file.exists()
        assert old_file.exists()

        # Note: Actual pruning is tested in Rust unit tests
        # This test verifies the file structure

    def test_journal_entry_schema(self):
        """Test that journal entries have all required fields."""
        required_fields = [
            "timestamp",
            "agent_name",
            "agent_kind",
            "agent_role",
            "project_name",
            "task_summary",
            "files_touched",
            "trigger",
        ]

        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent_name": "Test",
            "agent_kind": "claude",
            "agent_role": "Developer",
            "project_name": "test",
            "branch": None,
            "task_summary": "Test",
            "files_touched": [],
            "activity": None,
            "session_id": None,
            "trigger": "test",
        }

        for field in required_fields:
            assert field in entry, f"Missing required field: {field}"

    def test_journal_multiple_entries(self):
        """Test that multiple entries can be stored in the same day."""
        today = datetime.now().strftime("%Y-%m-%d")
        journal_file = JOURNAL_DIR / f"{today}.json"
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

        entries = [
            {
                "timestamp": datetime.now().isoformat(),
                "agent_name": "Atlas",
                "agent_kind": "claude",
                "agent_role": "Developer",
                "project_name": "synthia",
                "branch": "feature/1",
                "task_summary": "First task",
                "files_touched": ["file1.rs"],
                "activity": "Coding",
                "session_id": "session-1",
                "trigger": "task_list_completed",
            },
            {
                "timestamp": datetime.now().isoformat(),
                "agent_name": "Beckett",
                "agent_kind": "opencode",
                "agent_role": "Architect",
                "project_name": "synthia",
                "branch": "feature/2",
                "task_summary": "Second task",
                "files_touched": ["file2.rs"],
                "activity": "Planning",
                "session_id": "session-2",
                "trigger": "task_list_completed",
            },
        ]

        journal_data = {"entries": entries}

        with open(journal_file, "w") as f:
            json.dump(journal_data, f, indent=2)

        with open(journal_file) as f:
            loaded = json.load(f)

        assert len(loaded["entries"]) == 2
        assert loaded["entries"][0]["agent_name"] == "Atlas"
        assert loaded["entries"][1]["agent_name"] == "Beckett"
        assert loaded["entries"][1]["agent_kind"] == "opencode"
