"""Tests for synthia.display module."""

import pytest

from synthia.display import get_display_server, is_wayland, is_x11


class TestIsWayland:
    """Tests for is_wayland function."""

    def test_returns_true_when_wayland_display_set(self, clean_env, monkeypatch):
        """is_wayland returns True when WAYLAND_DISPLAY is set."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        assert is_wayland() is True

    def test_returns_false_when_not_set(self, clean_env):
        """is_wayland returns False when WAYLAND_DISPLAY is not set."""
        assert is_wayland() is False


class TestIsX11:
    """Tests for is_x11 function."""

    def test_returns_true_when_display_set_and_no_wayland(self, clean_env, monkeypatch):
        """is_x11 returns True when DISPLAY is set and WAYLAND_DISPLAY is not."""
        monkeypatch.setenv("DISPLAY", ":0")

        assert is_x11() is True

    def test_returns_false_when_wayland_also_set(self, clean_env, monkeypatch):
        """is_x11 returns False when running under XWayland (both set)."""
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        assert is_x11() is False

    def test_returns_false_when_display_not_set(self, clean_env):
        """is_x11 returns False when DISPLAY is not set."""
        assert is_x11() is False


class TestGetDisplayServer:
    """Tests for get_display_server function."""

    def test_returns_wayland_when_wayland(self, clean_env, monkeypatch):
        """get_display_server returns 'wayland' when running under Wayland."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        assert get_display_server() == "wayland"

    def test_returns_x11_when_x11(self, clean_env, monkeypatch):
        """get_display_server returns 'x11' when running under X11."""
        monkeypatch.setenv("DISPLAY", ":0")

        assert get_display_server() == "x11"

    def test_returns_unknown_when_neither(self, clean_env):
        """get_display_server returns 'unknown' when no display server detected."""
        assert get_display_server() == "unknown"
