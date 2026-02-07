"""Tests for inbox.py functions."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from synthia.remote import inbox


@pytest.fixture
def inbox_dir(tmp_path, monkeypatch):
    """Set up a temporary inbox directory for testing."""
    fake_inbox_dir = tmp_path / "inbox"
    fake_inbox_dir.mkdir(parents=True, exist_ok=True)

    fake_files_dir = fake_inbox_dir / "files"
    fake_files_dir.mkdir(parents=True, exist_ok=True)

    fake_inbox_file = fake_inbox_dir / "inbox.json"

    monkeypatch.setattr(inbox, "get_inbox_dir", lambda: fake_inbox_dir)
    monkeypatch.setattr(inbox, "get_files_dir", lambda: fake_files_dir)
    monkeypatch.setattr(inbox, "get_inbox_file", lambda: fake_inbox_file)

    return {
        "inbox_dir": fake_inbox_dir,
        "files_dir": fake_files_dir,
        "inbox_file": fake_inbox_file,
    }


class TestLoadInbox:
    """Tests for load_inbox function."""

    def test_returns_empty_list_when_no_file(self, inbox_dir):
        """Return empty list when inbox.json does not exist."""
        result = inbox.load_inbox()
        assert result == []

    def test_roundtrip_save_and_load(self, inbox_dir):
        """Save and load items round-trip correctly."""
        items = [
            {"id": "abc123", "type": "file", "filename": "test.txt", "opened": False},
            {"id": "def456", "type": "url", "filename": "page.html", "opened": True},
        ]
        inbox.save_inbox(items)

        result = inbox.load_inbox()
        assert result == items
        assert len(result) == 2


class TestAddInboxItem:
    """Tests for add_inbox_item function."""

    def test_creates_item_with_uuid_and_timestamp(self, inbox_dir):
        """New item has UUID id and timestamp."""
        item = inbox.add_inbox_item(
            item_type="file",
            filename="document.pdf",
            path="/tmp/document.pdf",
            size_bytes=1024,
            from_user="test_user",
        )

        assert "id" in item
        assert len(item["id"]) == 36  # UUID format
        assert "received_at" in item
        assert item["opened"] is False
        assert item["type"] == "file"
        assert item["filename"] == "document.pdf"

    def test_caps_at_50_items(self, inbox_dir):
        """Inbox is capped at 50 items."""
        # Add 55 items
        for i in range(55):
            inbox.add_inbox_item(
                item_type="file",
                filename=f"file_{i}.txt",
            )

        items = inbox.load_inbox()
        assert len(items) == 50

    def test_inserts_at_front(self, inbox_dir):
        """New items are inserted at the front (newest first)."""
        inbox.add_inbox_item(item_type="file", filename="first.txt")
        inbox.add_inbox_item(item_type="file", filename="second.txt")
        inbox.add_inbox_item(item_type="file", filename="third.txt")

        items = inbox.load_inbox()
        assert items[0]["filename"] == "third.txt"
        assert items[1]["filename"] == "second.txt"
        assert items[2]["filename"] == "first.txt"


class TestMarkItemOpened:
    """Tests for mark_item_opened function."""

    def test_sets_opened_flag(self, inbox_dir):
        """Mark item as opened sets opened to True."""
        item = inbox.add_inbox_item(item_type="file", filename="test.txt")
        assert item["opened"] is False

        inbox.mark_item_opened(item["id"])

        items = inbox.load_inbox()
        assert items[0]["opened"] is True

    def test_ignores_unknown_id(self, inbox_dir):
        """Marking unknown ID does not raise error."""
        inbox.add_inbox_item(item_type="file", filename="test.txt")

        # Should not raise
        inbox.mark_item_opened("nonexistent-id-12345")

        # Original item unchanged
        items = inbox.load_inbox()
        assert len(items) == 1
        assert items[0]["opened"] is False


class TestDeleteInboxItem:
    """Tests for delete_inbox_item function."""

    def test_removes_item_from_list(self, inbox_dir):
        """Delete removes item from inbox list."""
        item1 = inbox.add_inbox_item(item_type="file", filename="keep.txt")
        item2 = inbox.add_inbox_item(item_type="file", filename="delete.txt")

        result = inbox.delete_inbox_item(item2["id"])

        assert result is True
        items = inbox.load_inbox()
        assert len(items) == 1
        assert items[0]["id"] == item1["id"]

    def test_deletes_associated_file(self, inbox_dir):
        """Delete removes associated file from files directory."""
        files_dir = inbox_dir["files_dir"]
        test_file = files_dir / "test_document.pdf"
        test_file.write_text("test content")

        item = inbox.add_inbox_item(
            item_type="file",
            filename="test_document.pdf",
            path=str(test_file),
        )

        assert test_file.exists()

        inbox.delete_inbox_item(item["id"])

        assert not test_file.exists()

    def test_returns_false_for_unknown_id(self, inbox_dir):
        """Delete returns False for unknown item ID."""
        inbox.add_inbox_item(item_type="file", filename="test.txt")

        result = inbox.delete_inbox_item("nonexistent-id-12345")

        assert result is False


class TestClearInbox:
    """Tests for clear_inbox function."""

    def test_removes_all_items(self, inbox_dir):
        """Clear removes all items from inbox."""
        inbox.add_inbox_item(item_type="file", filename="file1.txt")
        inbox.add_inbox_item(item_type="file", filename="file2.txt")
        inbox.add_inbox_item(item_type="file", filename="file3.txt")

        assert len(inbox.load_inbox()) == 3

        inbox.clear_inbox()

        assert len(inbox.load_inbox()) == 0

    def test_deletes_all_associated_files(self, inbox_dir):
        """Clear deletes all files in the files directory."""
        files_dir = inbox_dir["files_dir"]

        # Create some files
        file1 = files_dir / "doc1.pdf"
        file2 = files_dir / "doc2.pdf"
        file3 = files_dir / "doc3.pdf"

        file1.write_text("content 1")
        file2.write_text("content 2")
        file3.write_text("content 3")

        inbox.add_inbox_item(item_type="file", filename="doc1.pdf", path=str(file1))
        inbox.add_inbox_item(item_type="file", filename="doc2.pdf", path=str(file2))
        inbox.add_inbox_item(item_type="file", filename="doc3.pdf", path=str(file3))

        assert file1.exists()
        assert file2.exists()
        assert file3.exists()

        inbox.clear_inbox()

        assert not file1.exists()
        assert not file2.exists()
        assert not file3.exists()


class TestGetInboxItems:
    """Tests for get_inbox_items function."""

    def test_returns_all_items(self, inbox_dir):
        """Get inbox items returns all items in order."""
        inbox.add_inbox_item(item_type="file", filename="first.txt")
        inbox.add_inbox_item(item_type="url", filename="second.html", url="https://example.com")
        inbox.add_inbox_item(item_type="file", filename="third.pdf")

        items = inbox.get_inbox_items()

        assert len(items) == 3
        assert items[0]["filename"] == "third.pdf"
        assert items[1]["filename"] == "second.html"
        assert items[2]["filename"] == "first.txt"
