"""Text output for Synthia with Wayland and X11 support."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

from .display import is_wayland

logger = logging.getLogger(__name__)

# Timeout for typing operations (seconds)
_TYPING_TIMEOUT = 10

# Wezterm Flatpak command (detected once at import)
_WEZTERM_CMD = None


def _find_wezterm_cli() -> list[str] | None:
    """Find the wezterm CLI command (native or Flatpak)."""
    if shutil.which("wezterm"):
        return ["wezterm"]
    # Check Flatpak
    try:
        result = subprocess.run(
            ["flatpak", "run", "org.wezfurlong.wezterm", "cli", "list"],
            capture_output=True,
            timeout=3,
        )
        if result.returncode == 0:
            return ["flatpak", "run", "org.wezfurlong.wezterm"]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _get_wezterm_cmd() -> list[str] | None:
    """Get cached wezterm command."""
    global _WEZTERM_CMD
    if _WEZTERM_CMD is None:
        _WEZTERM_CMD = _find_wezterm_cli() or []
    return _WEZTERM_CMD if _WEZTERM_CMD else None


def type_text(text: str) -> bool:
    """Type text at the current cursor position.

    Priority order:
    1. Wezterm CLI send-text (if focused window is Wezterm)
    2. Clipboard paste via wl-copy + wtype Ctrl+V (Wayland)
    3. Direct wtype (Wayland, some compositors)
    4. ydotool (Wayland fallback)
    5. xdotool (X11)
    """
    if not text:
        return False

    if is_wayland():
        # Wezterm CLI is the most reliable for terminal input
        if _type_with_wezterm_cli(text):
            return True
        # Clipboard paste for other Wayland apps
        if _type_with_clipboard_paste(text):
            return True
        # Direct wtype (works on Sway, some GNOME versions)
        if _type_with_wtype(text):
            return True
        # ydotool as last Wayland fallback
        if _type_with_ydotool(text):
            return True

    # Fallback to xdotool (X11 or XWayland)
    return _type_with_xdotool(text)


def _type_with_wezterm_cli(text: str) -> bool:
    """Type text directly into Wezterm using its CLI.

    This bypasses all keyboard simulation and works perfectly on any
    compositor. Only works when the focused pane is in Wezterm.
    """
    cmd = _get_wezterm_cmd()
    if not cmd:
        return False

    try:
        # Get the focused pane - if this fails, Wezterm isn't active
        result = subprocess.run(
            [*cmd, "cli", "get-pane-direction", "Next"],
            capture_output=True,
            timeout=2,
        )
        # Even if get-pane-direction fails, send-text to the active pane works

        subprocess.run(
            [*cmd, "cli", "send-text", "--no-paste", text],
            check=True,
            timeout=_TYPING_TIMEOUT,
        )
        logger.info("Typed (wezterm cli): %s%s", text[:50], "..." if len(text) > 50 else "")
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError:
        # Wezterm CLI not available or no active pane
        return False
    except subprocess.TimeoutExpired:
        logger.error("wezterm cli timed out")
        return False


def _type_with_clipboard_paste(text: str) -> bool:
    """Type text by copying to clipboard and simulating Ctrl+V.

    Works on most Wayland apps. May not work in terminals that require
    Ctrl+Shift+V for paste.
    """
    try:
        # Save current clipboard contents
        old_clipboard = None
        try:
            result = subprocess.run(
                ["wl-paste", "--no-newline"],
                capture_output=True,
                timeout=2,
            )
            if result.returncode == 0:
                old_clipboard = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Copy text to clipboard
        subprocess.run(
            ["wl-copy", "--", text],
            check=True,
            timeout=_TYPING_TIMEOUT,
        )

        time.sleep(0.05)

        # Simulate Ctrl+V paste
        subprocess.run(
            ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"],
            check=True,
            timeout=_TYPING_TIMEOUT,
        )

        logger.info("Typed (clipboard paste): %s%s", text[:50], "..." if len(text) > 50 else "")

        # Restore previous clipboard after a brief delay
        if old_clipboard is not None:
            time.sleep(0.1)
            subprocess.run(
                ["wl-copy", "--"],
                input=old_clipboard,
                timeout=2,
            )

        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError as e:
        logger.error("Clipboard paste error: %s", e)
        return False
    except subprocess.TimeoutExpired:
        logger.error("Clipboard paste timed out")
        return False


def _type_with_wtype(text: str) -> bool:
    """Type text using wtype (Wayland-native)."""
    try:
        subprocess.run(["wtype", "--", text], check=True, timeout=_TYPING_TIMEOUT)
        logger.info("Typed (wtype): %s%s", text[:50], "..." if len(text) > 50 else "")
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError as e:
        logger.error("wtype error: %s", e)
        return False
    except subprocess.TimeoutExpired:
        logger.error("wtype timed out")
        return False


def _type_with_ydotool(text: str) -> bool:
    """Type text using ydotool (works on both Wayland and X11)."""
    try:
        subprocess.run(["ydotool", "type", "--", text], check=True, timeout=_TYPING_TIMEOUT)
        logger.info("Typed (ydotool): %s%s", text[:50], "..." if len(text) > 50 else "")
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError as e:
        logger.error("ydotool error: %s", e)
        return False
    except subprocess.TimeoutExpired:
        logger.error("ydotool timed out")
        return False


def _type_with_xdotool(text: str) -> bool:
    """Type text using xdotool (X11 only)."""
    try:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--", text],
            check=True,
            timeout=_TYPING_TIMEOUT,
        )
        logger.info("Typed (xdotool): %s%s", text[:50], "..." if len(text) > 50 else "")
        return True
    except FileNotFoundError:
        logger.error("No typing tool found. Install wtype (Wayland) or xdotool (X11)")
        return False
    except subprocess.CalledProcessError as e:
        logger.error("xdotool error: %s", e)
        return False
    except subprocess.TimeoutExpired:
        logger.error("xdotool timed out")
        return False
