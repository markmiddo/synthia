"""Text output for Synthia with Wayland and X11 support."""

import subprocess

from .display import is_wayland


def type_text(text: str) -> bool:
    """Type text at the current cursor position.

    Uses wtype on Wayland, falls back to xdotool on X11.
    """
    if not text:
        return False

    # Try wtype first on Wayland
    if is_wayland():
        if _type_with_wtype(text):
            return True
        # Try ydotool as Wayland fallback
        if _type_with_ydotool(text):
            return True

    # Fallback to xdotool (X11 or XWayland)
    return _type_with_xdotool(text)


def _type_with_wtype(text: str) -> bool:
    """Type text using wtype (Wayland-native)."""
    try:
        subprocess.run(
            ["wtype", "--", text],
            check=True,
            timeout=10,
        )
        print(f"⌨️  Typed (wtype): {text[:50]}{'...' if len(text) > 50 else ''}")
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ wtype error: {e}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ wtype timed out")
        return False


def _type_with_ydotool(text: str) -> bool:
    """Type text using ydotool (works on both Wayland and X11)."""
    try:
        subprocess.run(
            ["ydotool", "type", "--", text],
            check=True,
            timeout=10,
        )
        print(f"⌨️  Typed (ydotool): {text[:50]}{'...' if len(text) > 50 else ''}")
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ ydotool error: {e}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ ydotool timed out")
        return False


def _type_with_xdotool(text: str) -> bool:
    """Type text using xdotool (X11 only)."""
    try:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--", text],
            check=True,
            timeout=10,
        )
        print(f"⌨️  Typed (xdotool): {text[:50]}{'...' if len(text) > 50 else ''}")
        return True
    except FileNotFoundError:
        print("❌ No typing tool found. Install wtype (Wayland) or xdotool (X11)")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ xdotool error: {e}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ xdotool timed out")
        return False
