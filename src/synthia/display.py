"""Display server detection utility for Synthia."""

import os


def is_wayland() -> bool:
    """Check if running on Wayland."""
    return bool(os.environ.get('WAYLAND_DISPLAY'))


def is_x11() -> bool:
    """Check if running on X11 (and not Wayland via XWayland)."""
    return bool(os.environ.get('DISPLAY')) and not is_wayland()


def get_display_server() -> str:
    """Get the current display server type."""
    if is_wayland():
        return 'wayland'
    elif is_x11():
        return 'x11'
    return 'unknown'
