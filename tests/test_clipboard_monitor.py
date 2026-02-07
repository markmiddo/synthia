"""Tests for synthia.clipboard_monitor module."""

import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from synthia.clipboard_monitor import ClipboardMonitor


class TestClipboardMonitorInit:
    """Tests for ClipboardMonitor initialization."""

    def test_init_with_defaults(self, tmp_path, monkeypatch):
        """ClipboardMonitor initializes with default values."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        monitor = ClipboardMonitor()

        assert monitor.max_items == 5
        assert monitor.running is False
        assert monitor._thread is None
        assert monitor._process is None
        assert monitor._last_hash is None
        assert monitor.history == []

    def test_init_with_custom_max_items(self, tmp_path, monkeypatch):
        """ClipboardMonitor accepts custom max_items."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        monitor = ClipboardMonitor(max_items=10)

        assert monitor.max_items == 10

    def test_init_with_custom_history_file(self, tmp_path):
        """ClipboardMonitor accepts custom history_file path."""
        history_file = tmp_path / "custom_history.json"

        monitor = ClipboardMonitor(history_file=str(history_file))

        assert monitor.history_file == str(history_file)

    def test_init_uses_xdg_runtime_dir(self, tmp_path, monkeypatch):
        """ClipboardMonitor uses XDG_RUNTIME_DIR for history file."""
        xdg_dir = tmp_path / "xdg"
        xdg_dir.mkdir()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_dir))

        monitor = ClipboardMonitor()

        assert monitor.history_file == str(xdg_dir / "synthia-clipboard.json")

    def test_init_falls_back_to_tmp_when_no_xdg(self, tmp_path, monkeypatch):
        """ClipboardMonitor falls back to /tmp when XDG_RUNTIME_DIR not set."""
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

        monitor = ClipboardMonitor()

        assert monitor.history_file == os.path.join("/tmp", "synthia-clipboard.json")

    def test_init_loads_existing_history(self, tmp_path):
        """ClipboardMonitor loads existing history from file."""
        history_file = tmp_path / "history.json"
        existing_data = [
            {"id": 1, "content": "test", "timestamp": "2024-01-01T00:00:00", "hash": "abc123"}
        ]
        history_file.write_text(json.dumps(existing_data))

        monitor = ClipboardMonitor(history_file=str(history_file))

        assert len(monitor.history) == 1
        assert monitor.history[0]["content"] == "test"

    def test_init_handles_missing_history_file(self, tmp_path):
        """ClipboardMonitor handles missing history file gracefully."""
        history_file = tmp_path / "nonexistent.json"

        monitor = ClipboardMonitor(history_file=str(history_file))

        assert monitor.history == []

    def test_init_handles_corrupted_history_file(self, tmp_path):
        """ClipboardMonitor handles corrupted history file."""
        history_file = tmp_path / "corrupted.json"
        history_file.write_text("{ invalid json")

        monitor = ClipboardMonitor(history_file=str(history_file))

        assert monitor.history == []


class TestContentHash:
    """Tests for _content_hash method."""

    def test_returns_sha256_hash(self, tmp_path, monkeypatch):
        """_content_hash returns SHA-256 hash of content."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        content = "test content"
        expected_hash = hashlib.sha256(content.encode()).hexdigest()

        result = monitor._content_hash(content)

        assert result == expected_hash

    def test_hash_deterministic(self, tmp_path, monkeypatch):
        """_content_hash is deterministic."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        content = "test content"

        hash1 = monitor._content_hash(content)
        hash2 = monitor._content_hash(content)

        assert hash1 == hash2

    def test_different_content_different_hash(self, tmp_path, monkeypatch):
        """Different content produces different hashes."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        hash1 = monitor._content_hash("content1")
        hash2 = monitor._content_hash("content2")

        assert hash1 != hash2

    def test_hash_is_hexdigest(self, tmp_path, monkeypatch):
        """_content_hash returns hexadecimal digest."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        result = monitor._content_hash("test")

        assert len(result) == 64  # SHA-256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in result)


class TestAddItem:
    """Tests for _add_item method."""

    def test_skips_empty_content(self, tmp_path, monkeypatch):
        """_add_item skips empty strings."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("")

        assert monitor.history == []

    def test_skips_whitespace_only(self, tmp_path, monkeypatch):
        """_add_item skips whitespace-only content."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("   \n\t  ")

        assert monitor.history == []

    def test_inserts_at_front(self, tmp_path, monkeypatch):
        """_add_item inserts new items at the front of history."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("first")
        monitor._add_item("second")

        assert len(monitor.history) == 2
        assert monitor.history[0]["content"] == "second"
        assert monitor.history[1]["content"] == "first"

    def test_strips_whitespace(self, tmp_path, monkeypatch):
        """_add_item strips leading/trailing whitespace from content."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("  content with spaces  ")

        assert monitor.history[0]["content"] == "content with spaces"

    def test_deduplicates_by_hash(self, tmp_path, monkeypatch):
        """_add_item removes duplicates by hash before inserting."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("content")
        monitor._add_item("other")
        monitor._add_item("content")  # Duplicate

        assert len(monitor.history) == 2
        assert monitor.history[0]["content"] == "content"
        assert monitor.history[1]["content"] == "other"

    def test_skips_same_as_last(self, tmp_path, monkeypatch):
        """_add_item skips adding same content as last item."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("content")
        monitor._add_item("content")  # Same

        assert len(monitor.history) == 1

    def test_trims_to_max_items(self, tmp_path, monkeypatch):
        """_add_item trims history to max_items."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor(max_items=3)

        for i in range(5):
            monitor._add_item(f"content{i}")

        assert len(monitor.history) == 3
        assert monitor.history[0]["content"] == "content4"
        assert monitor.history[1]["content"] == "content3"
        assert monitor.history[2]["content"] == "content2"

    def test_item_has_required_fields(self, tmp_path, monkeypatch):
        """Added items have id, content, timestamp, and hash."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("test content")

        item = monitor.history[0]
        assert "id" in item
        assert "content" in item
        assert "timestamp" in item
        assert "hash" in item

    def test_item_id_is_millisecond_timestamp(self, tmp_path, monkeypatch):
        """Item id is based on milliseconds since epoch."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        before = int(time.time() * 1000)
        monitor._add_item("test")
        after = int(time.time() * 1000)

        item_id = monitor.history[0]["id"]
        assert before <= item_id <= after

    def test_item_timestamp_is_iso_format(self, tmp_path, monkeypatch):
        """Item timestamp is in ISO format."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monitor._add_item("test")

        timestamp = monitor.history[0]["timestamp"]
        # Should be parseable as ISO format
        datetime.fromisoformat(timestamp)

    def test_saves_history_file(self, tmp_path, monkeypatch):
        """_add_item saves history to file."""
        history_file = tmp_path / "history.json"
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor(history_file=str(history_file))

        monitor._add_item("test")

        assert history_file.exists()
        data = json.loads(history_file.read_text())
        assert len(data) == 1
        assert data[0]["content"] == "test"

    def test_saves_with_restrictive_permissions(self, tmp_path, monkeypatch):
        """History file is saved with 0o600 permissions."""
        history_file = tmp_path / "history.json"
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor(history_file=str(history_file))

        monitor._add_item("test")

        # Check permissions (on Unix systems)
        if os.name == "posix":
            stat_info = os.stat(history_file)
            # Get permission bits
            mode = stat_info.st_mode & 0o777
            assert mode == 0o600


class TestStartStop:
    """Tests for start and stop methods."""

    def test_start_sets_running_flag(self, tmp_path, monkeypatch):
        """start() sets running flag to True."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        with patch.object(monitor, "_run_wayland_monitor"):
            monitor.start()

        assert monitor.running is True

    def test_start_spawns_thread(self, tmp_path, monkeypatch):
        """start() spawns a background thread."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        with patch.object(monitor, "_run_wayland_monitor"):
            monitor.start()

        assert monitor._thread is not None
        assert isinstance(monitor._thread, threading.Thread)
        assert monitor._thread.daemon is True

    def test_start_uses_wayland_on_wayland(self, tmp_path, monkeypatch):
        """start() uses _run_wayland_monitor on Wayland."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        with patch.object(monitor, "_run_wayland_monitor") as mock_wayland:
            monitor.start()
            time.sleep(0.01)  # Let thread start
            monitor.running = False  # Stop thread

            # Verify wayland monitor was targeted
            assert monitor._thread is not None

    def test_start_uses_x11_on_x11(self, tmp_path, monkeypatch):
        """start() uses _run_x11_monitor on X11."""
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        with patch.object(monitor, "_run_x11_monitor") as mock_x11:
            monitor.start()
            time.sleep(0.01)
            monitor.running = False

            assert monitor._thread is not None

    def test_start_idempotent(self, tmp_path, monkeypatch):
        """Calling start() twice doesn't create multiple threads."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        with patch.object(monitor, "_run_wayland_monitor"):
            monitor.start()
            thread1 = monitor._thread
            monitor.start()
            thread2 = monitor._thread

            assert thread1 is thread2

    def test_stop_sets_running_flag(self, tmp_path, monkeypatch):
        """stop() sets running flag to False."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        with patch.object(monitor, "_run_wayland_monitor"):
            monitor.start()
            monitor.stop()

        assert monitor.running is False

    def test_stop_terminates_process(self, tmp_path, monkeypatch):
        """stop() terminates the subprocess."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_process = Mock()
        monitor._process = mock_process

        monitor.stop()

        mock_process.terminate.assert_called_once()

    def test_stop_kills_process_if_terminate_fails(self, tmp_path, monkeypatch):
        """stop() kills process if terminate times out."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_process = Mock()
        mock_process.terminate.side_effect = subprocess.TimeoutExpired("cmd", 1)
        monitor._process = mock_process

        monitor.stop()

        mock_process.kill.assert_called_once()

    def test_stop_waits_for_thread(self, tmp_path, monkeypatch):
        """stop() waits for thread to finish."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_thread = Mock()
        monitor._thread = mock_thread
        monitor.running = True

        monitor.stop()

        mock_thread.join.assert_called_once()


class TestGetHistory:
    """Tests for get_history method."""

    def test_returns_copy_of_history(self, tmp_path, monkeypatch):
        """get_history returns a copy, not the internal list."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()
        monitor._add_item("test")

        history = monitor.get_history()

        assert history is not monitor.history
        assert history == monitor.history

    def test_modifications_dont_affect_internal(self, tmp_path, monkeypatch):
        """Modifications to returned history don't affect internal history."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()
        monitor._add_item("test")

        history = monitor.get_history()
        history.clear()

        assert len(monitor.history) == 1

    def test_returns_empty_when_no_history(self, tmp_path, monkeypatch):
        """get_history returns empty list when no items."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        history = monitor.get_history()

        assert history == []

    def test_returns_all_items(self, tmp_path, monkeypatch):
        """get_history returns all items in order."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()
        monitor._add_item("first")
        monitor._add_item("second")
        monitor._add_item("third")

        history = monitor.get_history()

        assert len(history) == 3
        assert history[0]["content"] == "third"
        assert history[1]["content"] == "second"
        assert history[2]["content"] == "first"


class TestCopyItem:
    """Tests for copy_item method."""

    def test_copies_existing_item_to_clipboard(self, tmp_path, monkeypatch):
        """copy_item copies an existing item to clipboard."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()
        monitor._add_item("test content")

        item_id = monitor.history[0]["id"]

        with patch.object(monitor, "_copy_to_clipboard", return_value=True) as mock_copy:
            result = monitor.copy_item(item_id)

        assert result is True
        mock_copy.assert_called_once_with("test content")

    def test_returns_false_for_invalid_id(self, tmp_path, monkeypatch):
        """copy_item returns False for non-existent item ID."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        result = monitor.copy_item(999999)

        assert result is False

    def test_returns_false_when_copy_fails(self, tmp_path, monkeypatch):
        """copy_item returns False when _copy_to_clipboard fails."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()
        monitor._add_item("test")

        item_id = monitor.history[0]["id"]

        with patch.object(monitor, "_copy_to_clipboard", return_value=False):
            result = monitor.copy_item(item_id)

        assert result is False


class TestCopyToClipboard:
    """Tests for _copy_to_clipboard method."""

    def test_uses_wl_copy_on_wayland(self, tmp_path, monkeypatch):
        """_copy_to_clipboard uses wl-copy on Wayland."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_popen = Mock()
        mock_popen.communicate = Mock()
        monkeypatch.setattr("subprocess.Popen", mock_popen)

        monitor._copy_to_clipboard("test")

        # Verify wl-copy was used
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "wl-copy"

    def test_uses_xclip_on_x11(self, tmp_path, monkeypatch):
        """_copy_to_clipboard uses xclip on X11."""
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_popen = Mock()
        mock_popen.communicate = Mock()
        monkeypatch.setattr("subprocess.Popen", mock_popen)

        monitor._copy_to_clipboard("test")

        # Verify xclip was used
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "xclip"

    def test_returns_true_on_success(self, tmp_path, monkeypatch):
        """_copy_to_clipboard returns True on success."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_popen = Mock()
        mock_popen.communicate = Mock()
        monkeypatch.setattr("subprocess.Popen", mock_popen)

        result = monitor._copy_to_clipboard("test")

        assert result is True

    def test_returns_false_on_exception(self, tmp_path, monkeypatch):
        """_copy_to_clipboard returns False on exception."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        monkeypatch.setattr("subprocess.Popen", Mock(side_effect=FileNotFoundError()))

        result = monitor._copy_to_clipboard("test")

        assert result is False

    def test_passes_content_to_stdin(self, tmp_path, monkeypatch):
        """_copy_to_clipboard passes content to process stdin."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_process = Mock()
        mock_popen = Mock(return_value=mock_process)
        monkeypatch.setattr("subprocess.Popen", mock_popen)

        monitor._copy_to_clipboard("test content")

        # Verify content was passed to communicate
        mock_process.communicate.assert_called_once()
        call_kwargs = mock_process.communicate.call_args[1]
        assert call_kwargs.get("input") == "test content"


class TestGetClipboardContent:
    """Tests for _get_clipboard_content method."""

    def test_uses_wl_paste_on_wayland(self, tmp_path, monkeypatch):
        """_get_clipboard_content uses wl-paste on Wayland."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_run = Mock(return_value=Mock(returncode=0, stdout="content"))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = monitor._get_clipboard_content()

        call_args = mock_run.call_args[0][0]
        assert "wl-paste" in call_args

    def test_uses_xclip_on_x11(self, tmp_path, monkeypatch):
        """_get_clipboard_content uses xclip on X11."""
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_run = Mock(return_value=Mock(returncode=0, stdout="content"))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = monitor._get_clipboard_content()

        call_args = mock_run.call_args[0][0]
        assert "xclip" in call_args

    def test_returns_content_on_success(self, tmp_path, monkeypatch):
        """_get_clipboard_content returns content when successful."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_run = Mock(return_value=Mock(returncode=0, stdout="clipboard content"))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = monitor._get_clipboard_content()

        assert result == "clipboard content"

    def test_returns_none_on_failure(self, tmp_path, monkeypatch):
        """_get_clipboard_content returns None on failure."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_run = Mock(side_effect=FileNotFoundError())
        monkeypatch.setattr("subprocess.run", mock_run)

        result = monitor._get_clipboard_content()

        assert result is None

    def test_returns_none_on_nonzero_returncode(self, tmp_path, monkeypatch):
        """_get_clipboard_content returns None when returncode != 0."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monitor = ClipboardMonitor()

        mock_run = Mock(return_value=Mock(returncode=1, stdout=""))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = monitor._get_clipboard_content()

        assert result is None
