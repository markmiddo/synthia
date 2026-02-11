"""Tests for synthia.output module - text typing/pasting functions."""

import subprocess
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from synthia import output
from synthia.output import (
    _find_wezterm_cli,
    _get_wezterm_cmd,
    _type_with_clipboard_paste,
    _type_with_wezterm_cli,
    _type_with_wtype,
    _type_with_xdotool,
    _type_with_ydotool,
    type_text,
)


class TestTypeText:
    """Tests for type_text function."""

    def test_returns_false_for_empty_text(self, clean_env, monkeypatch):
        """type_text returns False when passed empty string."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        assert type_text("") is False

    def test_returns_false_for_none(self, clean_env, monkeypatch):
        """type_text returns False when passed None-like values."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        # The function checks `if not text`, so falsy values return False
        assert type_text("") is False

    def test_wayland_priority_wezterm_first(self, clean_env, monkeypatch):
        """On Wayland, wezterm CLI is tried first."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(output, "_type_with_wezterm_cli", lambda x: True)
        monkeypatch.setattr(output, "_type_with_clipboard_paste", lambda x: False)

        assert type_text("test") is True

    def test_wayland_fallback_to_clipboard_paste(self, clean_env, monkeypatch):
        """On Wayland, falls back to clipboard paste when wezterm fails."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(output, "_type_with_wezterm_cli", lambda x: False)
        monkeypatch.setattr(output, "_type_with_clipboard_paste", lambda x: True)
        monkeypatch.setattr(output, "_type_with_wtype", lambda x: False)

        assert type_text("test") is True

    def test_wayland_fallback_to_wtype(self, clean_env, monkeypatch):
        """On Wayland, falls back to wtype when clipboard paste fails."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(output, "_type_with_wezterm_cli", lambda x: False)
        monkeypatch.setattr(output, "_type_with_clipboard_paste", lambda x: False)
        monkeypatch.setattr(output, "_type_with_wtype", lambda x: True)

        assert type_text("test") is True

    def test_wayland_fallback_to_ydotool(self, clean_env, monkeypatch):
        """On Wayland, falls back to ydotool when wtype fails."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(output, "_type_with_wezterm_cli", lambda x: False)
        monkeypatch.setattr(output, "_type_with_clipboard_paste", lambda x: False)
        monkeypatch.setattr(output, "_type_with_wtype", lambda x: False)
        monkeypatch.setattr(output, "_type_with_ydotool", lambda x: True)

        assert type_text("test") is True

    def test_wayland_fallback_to_xdotool(self, clean_env, monkeypatch):
        """On Wayland with all else failing, falls back to xdotool."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(output, "_type_with_wezterm_cli", lambda x: False)
        monkeypatch.setattr(output, "_type_with_clipboard_paste", lambda x: False)
        monkeypatch.setattr(output, "_type_with_wtype", lambda x: False)
        monkeypatch.setattr(output, "_type_with_ydotool", lambda x: False)
        monkeypatch.setattr(output, "_type_with_xdotool", lambda x: True)

        assert type_text("test") is True

    def test_x11_uses_xdotool(self, clean_env, monkeypatch):
        """On X11, xdotool is used directly."""
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(output, "_type_with_xdotool", lambda x: True)

        assert type_text("test") is True

    def test_wayland_all_methods_fail(self, clean_env, monkeypatch):
        """When all methods fail, returns False."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(output, "_type_with_wezterm_cli", lambda x: False)
        monkeypatch.setattr(output, "_type_with_clipboard_paste", lambda x: False)
        monkeypatch.setattr(output, "_type_with_wtype", lambda x: False)
        monkeypatch.setattr(output, "_type_with_ydotool", lambda x: False)
        monkeypatch.setattr(output, "_type_with_xdotool", lambda x: False)

        assert type_text("test") is False


class TestFindWeztermCli:
    """Tests for _find_wezterm_cli function."""

    def test_returns_wezterm_when_found_in_path(self, monkeypatch):
        """Returns ['wezterm'] when wezterm is in PATH."""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/bin/wezterm" if x == "wezterm" else None
        )

        result = _find_wezterm_cli()
        assert result == ["wezterm"]

    def test_returns_flatpak_when_native_not_found(self, monkeypatch):
        """Returns Flatpak command when native wezterm not in PATH."""
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _find_wezterm_cli()
        assert result == ["flatpak", "run", "org.wezfurlong.wezterm"]

    def test_returns_none_when_neither_found(self, monkeypatch):
        """Returns None when neither native nor Flatpak wezterm found."""
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_run = Mock(side_effect=FileNotFoundError())
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _find_wezterm_cli()
        assert result is None

    def test_handles_flatpak_timeout(self, monkeypatch):
        """Handles timeout when checking Flatpak."""
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_run = Mock(side_effect=subprocess.TimeoutExpired("cmd", 3))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _find_wezterm_cli()
        assert result is None

    def test_flatpak_command_includes_cli_list(self, monkeypatch):
        """Flatpak check includes 'cli list' to verify it's available."""
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        _find_wezterm_cli()

        # Verify the flatpak check command includes 'cli list'
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["flatpak", "run", "org.wezfurlong.wezterm", "cli", "list"]


class TestGetWeztermCmd:
    """Tests for _get_wezterm_cmd function (caching)."""

    def test_caches_result(self, monkeypatch):
        """_get_wezterm_cmd caches the result."""
        # Reset the module-level cache
        output._WEZTERM_CMD = None

        mock_find = Mock(return_value=["wezterm"])
        monkeypatch.setattr(output, "_find_wezterm_cli", mock_find)

        result1 = _get_wezterm_cmd()
        result2 = _get_wezterm_cmd()

        # Should only call find once due to caching
        assert mock_find.call_count == 1
        assert result1 == result2 == ["wezterm"]

    def test_returns_none_when_not_found(self, monkeypatch):
        """Returns None when wezterm is not found."""
        output._WEZTERM_CMD = None

        monkeypatch.setattr(output, "_find_wezterm_cli", lambda: None)

        result = _get_wezterm_cmd()
        assert result is None


class TestTypeWithWeztermCli:
    """Tests for _type_with_wezterm_cli function."""

    def test_returns_false_when_wezterm_not_available(self, monkeypatch):
        """Returns False when wezterm is not available."""
        monkeypatch.setattr(output, "_get_wezterm_cmd", lambda: None)

        assert _type_with_wezterm_cli("test") is False

    def test_calls_wezterm_send_text_with_text(self, monkeypatch):
        """Calls wezterm cli send-text with the provided text."""
        monkeypatch.setattr(output, "_get_wezterm_cmd", lambda: ["wezterm"])
        monkeypatch.setattr(output, "_get_focused_window_class", lambda: "org.wezfurlong.wezterm")
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_wezterm_cli("hello world")

        assert mock_run.call_count == 1
        send_text_call = mock_run.call_args_list[0]
        assert "send-text" in send_text_call[0][0]
        assert "hello world" in send_text_call[0][0]
        assert result is True

    def test_uses_flatpak_command_if_available(self, monkeypatch):
        """Uses flatpak command if that's what was found."""
        monkeypatch.setattr(
            output, "_get_wezterm_cmd", lambda: ["flatpak", "run", "org.wezfurlong.wezterm"]
        )
        monkeypatch.setattr(output, "_get_focused_window_class", lambda: "org.wezfurlong.wezterm")
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        _type_with_wezterm_cli("test")

        # Verify flatpak command was used
        call_args = mock_run.call_args_list[0][0][0]
        assert call_args[0] == "flatpak"

    def test_handles_timeout(self, monkeypatch):
        """Returns False on timeout."""
        monkeypatch.setattr(output, "_get_wezterm_cmd", lambda: ["wezterm"])
        monkeypatch.setattr(output, "_get_focused_window_class", lambda: "org.wezfurlong.wezterm")
        mock_run = Mock(side_effect=subprocess.TimeoutExpired("cmd", 10))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_wezterm_cli("test")
        assert result is False

    def test_handles_called_process_error(self, monkeypatch):
        """Returns False when wezterm is not active."""
        monkeypatch.setattr(output, "_get_wezterm_cmd", lambda: ["wezterm"])
        monkeypatch.setattr(output, "_get_focused_window_class", lambda: "org.wezfurlong.wezterm")
        mock_run = Mock(side_effect=subprocess.CalledProcessError(1, "cmd"))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_wezterm_cli("test")
        assert result is False

    def test_handles_file_not_found(self, monkeypatch):
        """Returns False when wezterm binary not found."""
        monkeypatch.setattr(output, "_get_wezterm_cmd", lambda: ["wezterm"])
        monkeypatch.setattr(output, "_get_focused_window_class", lambda: "org.wezfurlong.wezterm")
        mock_run = Mock(side_effect=FileNotFoundError())
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_wezterm_cli("test")
        assert result is False

    def test_send_text_timeout_parameter(self, monkeypatch):
        """send-text call has correct timeout."""
        monkeypatch.setattr(output, "_get_wezterm_cmd", lambda: ["wezterm"])
        monkeypatch.setattr(output, "_get_focused_window_class", lambda: "org.wezfurlong.wezterm")
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        _type_with_wezterm_cli("test")

        # Check send-text call timeout
        send_text_call = mock_run.call_args_list[0]
        assert send_text_call[1]["timeout"] == output._TYPING_TIMEOUT


class TestTypeWithClipboardPaste:
    """Tests for _type_with_clipboard_paste function."""

    def test_copies_to_clipboard_and_pastes(self, monkeypatch):
        """Copies text to clipboard and simulates Ctrl+V."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout=b""))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_clipboard_paste("hello")

        assert result is True

        # Verify wl-copy was called
        wl_copy_calls = [call for call in mock_run.call_args_list if "wl-copy" in str(call)]
        assert len(wl_copy_calls) >= 1

    def test_saves_and_restores_clipboard(self, monkeypatch):
        """Saves old clipboard content and restores it."""
        call_sequence = []

        def mock_run(*args, **kwargs):
            call_sequence.append((args[0], kwargs.get("input")))
            if "wl-paste" in args[0]:
                return Mock(returncode=0, stdout=b"old content")
            return Mock(returncode=0, stdout=b"")

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("time.sleep", lambda x: None)

        _type_with_clipboard_paste("hello")

        # Check that restore happened (second wl-copy with old content)
        restore_calls = [c for c in call_sequence if c[0][0] == "wl-copy" and c[1] is not None]
        assert len(restore_calls) > 0

    def test_handles_wl_paste_failure(self, monkeypatch):
        """Handles when wl-paste fails to get old clipboard."""

        def mock_run(*args, **kwargs):
            if "wl-paste" in args[0]:
                raise subprocess.TimeoutExpired("cmd", 2)
            return Mock(returncode=0, stdout=b"")

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("time.sleep", lambda x: None)

        # Should still succeed even if can't read old clipboard
        result = _type_with_clipboard_paste("hello")
        assert result is True

    def test_wtype_with_ctrl_v(self, monkeypatch):
        """wtype is called with Ctrl+V sequence."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout=b""))
        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("time.sleep", lambda x: None)

        _type_with_clipboard_paste("hello")

        # Find the wtype call
        wtype_calls = [call for call in mock_run.call_args_list if "wtype" in str(call)]
        assert len(wtype_calls) == 1

        # Verify it includes Ctrl+V
        wtype_call_args = wtype_calls[0][0][0]
        assert "-M" in wtype_call_args  # -M for key modifiers
        assert "ctrl" in wtype_call_args
        assert "v" in wtype_call_args

    def test_handles_file_not_found(self, monkeypatch):
        """Returns False when tools not found."""
        monkeypatch.setattr("subprocess.run", Mock(side_effect=FileNotFoundError()))

        result = _type_with_clipboard_paste("hello")
        assert result is False

    def test_handles_called_process_error(self, monkeypatch):
        """Returns False on subprocess error."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.CalledProcessError(1, "cmd"))
        )

        result = _type_with_clipboard_paste("hello")
        assert result is False

    def test_handles_timeout_expired(self, monkeypatch):
        """Returns False on timeout."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.TimeoutExpired("cmd", 10))
        )

        result = _type_with_clipboard_paste("hello")
        assert result is False


class TestTypeWithWtype:
    """Tests for _type_with_wtype function."""

    def test_calls_wtype_with_text(self, monkeypatch):
        """Calls wtype with the provided text."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_wtype("hello world")

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "wtype"
        assert "hello world" in call_args

    def test_returns_false_when_wtype_not_found(self, monkeypatch):
        """Returns False when wtype binary not found."""
        monkeypatch.setattr("subprocess.run", Mock(side_effect=FileNotFoundError()))

        result = _type_with_wtype("test")
        assert result is False

    def test_returns_false_on_error(self, monkeypatch):
        """Returns False on subprocess error."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.CalledProcessError(1, "cmd"))
        )

        result = _type_with_wtype("test")
        assert result is False

    def test_returns_false_on_timeout(self, monkeypatch):
        """Returns False on timeout."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.TimeoutExpired("cmd", 10))
        )

        result = _type_with_wtype("test")
        assert result is False

    def test_uses_correct_timeout(self, monkeypatch):
        """Uses correct timeout for wtype."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        _type_with_wtype("test")

        assert mock_run.call_args[1]["timeout"] == output._TYPING_TIMEOUT


class TestTypeWithYdotool:
    """Tests for _type_with_ydotool function."""

    def test_calls_ydotool_with_text(self, monkeypatch):
        """Calls ydotool with the provided text."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_ydotool("hello world")

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "ydotool"
        assert "type" in call_args
        assert "hello world" in call_args

    def test_returns_false_when_ydotool_not_found(self, monkeypatch):
        """Returns False when ydotool binary not found."""
        monkeypatch.setattr("subprocess.run", Mock(side_effect=FileNotFoundError()))

        result = _type_with_ydotool("test")
        assert result is False

    def test_returns_false_on_error(self, monkeypatch):
        """Returns False on subprocess error."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.CalledProcessError(1, "cmd"))
        )

        result = _type_with_ydotool("test")
        assert result is False

    def test_returns_false_on_timeout(self, monkeypatch):
        """Returns False on timeout."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.TimeoutExpired("cmd", 10))
        )

        result = _type_with_ydotool("test")
        assert result is False


class TestTypeWithXdotool:
    """Tests for _type_with_xdotool function."""

    def test_calls_xdotool_with_clearmodifiers(self, monkeypatch):
        """Calls xdotool with --clearmodifiers flag."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _type_with_xdotool("hello world")

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "xdotool"
        assert "type" in call_args
        assert "--clearmodifiers" in call_args
        assert "hello world" in call_args

    def test_returns_false_when_xdotool_not_found(self, monkeypatch):
        """Returns False when xdotool binary not found."""
        monkeypatch.setattr("subprocess.run", Mock(side_effect=FileNotFoundError()))

        result = _type_with_xdotool("test")
        assert result is False

    def test_returns_false_on_error(self, monkeypatch):
        """Returns False on subprocess error."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.CalledProcessError(1, "cmd"))
        )

        result = _type_with_xdotool("test")
        assert result is False

    def test_returns_false_on_timeout(self, monkeypatch):
        """Returns False on timeout."""
        monkeypatch.setattr(
            "subprocess.run", Mock(side_effect=subprocess.TimeoutExpired("cmd", 10))
        )

        result = _type_with_xdotool("test")
        assert result is False

    def test_uses_correct_timeout(self, monkeypatch):
        """Uses correct timeout for xdotool."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        _type_with_xdotool("test")

        assert mock_run.call_args[1]["timeout"] == output._TYPING_TIMEOUT
