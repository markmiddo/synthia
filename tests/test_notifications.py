"""Tests for synthia.notifications module."""

import subprocess
from unittest.mock import patch, call

import pytest

from synthia.notifications import (
    notify,
    notify_ready,
    notify_dictation,
    notify_assistant,
    notify_error,
    DEFAULT_TIMEOUT,
    ERROR_TIMEOUT,
)


class TestNotify:
    """Tests for the notify function."""

    @patch("synthia.notifications.subprocess.run")
    def test_notify_calls_subprocess_with_correct_args(self, mock_run):
        """notify should call subprocess.run with notify-send and all arguments."""
        notify("Test Title", "Test Message", icon="dialog-info", timeout=4000)

        mock_run.assert_called_once_with(
            [
                "notify-send",
                "--app-name=Synthia",
                "--icon=dialog-info",
                "--expire-time=4000",
                "Test Title",
                "Test Message",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("synthia.notifications.subprocess.run")
    def test_notify_uses_default_icon(self, mock_run):
        """notify should use audio-input-microphone as default icon."""
        notify("Title", "Message")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--icon=audio-input-microphone" in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_uses_default_timeout(self, mock_run):
        """notify should use DEFAULT_TIMEOUT when no timeout specified."""
        notify("Title", "Message")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert f"--expire-time={DEFAULT_TIMEOUT}" in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_handles_missing_notify_send(self, mock_run):
        """notify should handle FileNotFoundError gracefully when notify-send is missing."""
        mock_run.side_effect = FileNotFoundError("notify-send not found")

        # Should not raise
        notify("Title", "Message")

    @patch("synthia.notifications.subprocess.run")
    def test_notify_handles_generic_exception(self, mock_run):
        """notify should catch and log generic exceptions without raising."""
        mock_run.side_effect = OSError("some OS error")

        # Should not raise
        notify("Title", "Message")

    @patch("synthia.notifications.subprocess.run")
    def test_notify_includes_app_name(self, mock_run):
        """notify should always pass --app-name=Synthia."""
        notify("Title", "Message")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--app-name=Synthia" in cmd


class TestNotifyError:
    """Tests for notify_error function."""

    @patch("synthia.notifications.subprocess.run")
    def test_notify_error_uses_error_timeout(self, mock_run):
        """notify_error should use ERROR_TIMEOUT, not DEFAULT_TIMEOUT."""
        notify_error("Something went wrong")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert f"--expire-time={ERROR_TIMEOUT}" in cmd
        assert ERROR_TIMEOUT == 5000

    @patch("synthia.notifications.subprocess.run")
    def test_notify_error_uses_error_icon(self, mock_run):
        """notify_error should use dialog-error icon."""
        notify_error("Something went wrong")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--icon=dialog-error" in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_error_title(self, mock_run):
        """notify_error should use 'Synthia Error' as the title."""
        notify_error("Disk full")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "Synthia Error" in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_error_passes_message(self, mock_run):
        """notify_error should pass the error message as the body text."""
        notify_error("Connection lost")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "Connection lost" in cmd


class TestNotifyReady:
    """Tests for notify_ready function."""

    @patch("synthia.notifications.subprocess.run")
    def test_notify_ready_sends_notification(self, mock_run):
        """notify_ready should send a notification with the correct title and icon."""
        notify_ready()

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "Synthia" in cmd
        assert "--icon=audio-input-microphone" in cmd


class TestNotifyDictation:
    """Tests for notify_dictation function."""

    @patch("synthia.notifications.subprocess.run")
    def test_notify_dictation_sends_text(self, mock_run):
        """notify_dictation should send the dictated text in the notification."""
        notify_dictation("Hello world")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "Hello world" in cmd
        assert "Dictation" in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_dictation_truncates_long_text(self, mock_run):
        """notify_dictation should truncate text longer than 100 characters."""
        long_text = "a" * 150
        notify_dictation(long_text)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # The displayed text should be the first 100 chars + "..."
        expected_display = "a" * 100 + "..."
        assert expected_display in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_dictation_uses_edit_icon(self, mock_run):
        """notify_dictation should use the document-edit icon."""
        notify_dictation("test")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--icon=document-edit" in cmd


class TestNotifyAssistant:
    """Tests for notify_assistant function."""

    @patch("synthia.notifications.subprocess.run")
    def test_notify_assistant_sends_response(self, mock_run):
        """notify_assistant should send the assistant response."""
        notify_assistant("Here is your answer")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "Here is your answer" in cmd
        assert "Assistant" in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_assistant_truncates_long_response(self, mock_run):
        """notify_assistant should truncate responses longer than 100 characters."""
        long_response = "b" * 150
        notify_assistant(long_response)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        expected_display = "b" * 100 + "..."
        assert expected_display in cmd

    @patch("synthia.notifications.subprocess.run")
    def test_notify_assistant_uses_user_available_icon(self, mock_run):
        """notify_assistant should use the user-available icon."""
        notify_assistant("test")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--icon=user-available" in cmd


class TestConstants:
    """Tests for module-level constants."""

    def test_default_timeout_value(self):
        """DEFAULT_TIMEOUT should be 3000 milliseconds."""
        assert DEFAULT_TIMEOUT == 3000

    def test_error_timeout_value(self):
        """ERROR_TIMEOUT should be 5000 milliseconds."""
        assert ERROR_TIMEOUT == 5000

    def test_error_timeout_greater_than_default(self):
        """ERROR_TIMEOUT should be longer than DEFAULT_TIMEOUT."""
        assert ERROR_TIMEOUT > DEFAULT_TIMEOUT
