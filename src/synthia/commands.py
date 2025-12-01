"""Command execution for Synthia assistant."""

import subprocess
import os
from typing import Dict, Any, List
from synthia.output import type_text
from synthia.display import is_wayland


# Common app name mappings
APP_ALIASES = {
    "chrome": "google-chrome",
    "google chrome": "google-chrome",
    "terminal": "wezterm",
    "term": "wezterm",
    "wezterm": "wezterm",
    "wisdom": "wezterm",
    "wez term": "wezterm",
    "code": "zed",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "zed": "zed",
    "zed editor": "zed",
    "files": "nautilus",
    "file manager": "nautilus",
    "spotify": "spotify",
    "slack": "slack",
    "discord": "discord",
    "gimp": "gimp",
    "krita": "krita",
    "firefox": "firefox",
    "brave": "brave-browser",
    "zen": "zen",
    "zen browser": "zen",
    "zen-browser": "zen",
    "notes": "notes",
    "krita": "krita",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
}

# Flatpak app IDs (for apps installed via Flatpak)
FLATPAK_APPS = {
    "wezterm": "org.wezfurlong.wezterm",
    "zed": "dev.zed.Zed",
    "google-chrome": "com.google.Chrome",
    "zen": "app.zen_browser.zen",
    "notes": "io.github.nuttyartist.notes",
    "krita": "org.kde.krita",
    "telegram": "org.telegram.desktop",
    "whatsapp": "com.rtosta.zapzap",
    "zapzap": "com.rtosta.zapzap",
}


def _resolve_app_name(app: str) -> str:
    """Resolve app aliases to actual command names."""
    app_lower = app.lower().strip()
    return APP_ALIASES.get(app_lower, app_lower)


def open_app(app: str) -> bool:
    """Launch an application."""
    app_cmd = _resolve_app_name(app)

    # Check if it's a Flatpak app
    if app_cmd in FLATPAK_APPS:
        flatpak_id = FLATPAK_APPS[app_cmd]
        try:
            subprocess.Popen(
                ["flatpak", "run", flatpak_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            print(f"✅ Opened (Flatpak): {flatpak_id}")
            return True
        except Exception as e:
            print(f"❌ Error opening Flatpak {flatpak_id}: {e}")
            return False

    # Try regular command
    try:
        subprocess.Popen(
            [app_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"✅ Opened: {app_cmd}")
        return True
    except FileNotFoundError:
        print(f"❌ App not found: {app_cmd}")
        return False
    except Exception as e:
        print(f"❌ Error opening {app_cmd}: {e}")
        return False


def open_url(url: str, browser: str = "google-chrome") -> bool:
    """Open a URL in Chrome (Flatpak)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Use Chrome Flatpak
    try:
        subprocess.Popen(
            ["flatpak", "run", "com.google.Chrome", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"✅ Opened URL in Chrome: {url}")
        return True
    except Exception as e:
        print(f"❌ Error opening URL: {e}")
        return False


def _open_url_old(url: str, browser: str = "google-chrome") -> bool:
    """Old open_url - unused."""
    browser_cmd = "google-chrome"

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        subprocess.Popen(
            [browser_cmd, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"✅ Opened URL: {url}")
        return True
    except Exception as e:
        print(f"❌ Error opening URL: {e}")
        return False


def close_app(app: str) -> bool:
    """Close an application by name."""
    app_cmd = _resolve_app_name(app)

    try:
        subprocess.run(["pkill", "-f", app_cmd], check=False)
        print(f"✅ Closed: {app_cmd}")
        return True
    except Exception as e:
        print(f"❌ Error closing {app_cmd}: {e}")
        return False


def run_command(command: str) -> str:
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr
        print(f"✅ Command output: {output[:100]}...")
        return output.strip()
    except subprocess.TimeoutExpired:
        print("❌ Command timed out")
        return "Command timed out"
    except Exception as e:
        print(f"❌ Command error: {e}")
        return str(e)


# ============== VOLUME CONTROL ==============

def set_volume(level: int) -> bool:
    """Set system volume to a percentage (0-100)."""
    level = max(0, min(100, level))
    try:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"], check=True)
        print(f"✅ Volume set to {level}%")
        return True
    except Exception as e:
        print(f"❌ Volume error: {e}")
        return False


def change_volume(delta: int) -> bool:
    """Change volume by delta percentage (positive or negative)."""
    sign = "+" if delta >= 0 else ""
    try:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{delta}%"], check=True)
        print(f"✅ Volume changed by {sign}{delta}%")
        return True
    except Exception as e:
        print(f"❌ Volume error: {e}")
        return False


def mute(state: bool = True) -> bool:
    """Mute or unmute system audio."""
    try:
        value = "1" if state else "0"
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", value], check=True)
        print(f"✅ {'Muted' if state else 'Unmuted'}")
        return True
    except Exception as e:
        print(f"❌ Mute error: {e}")
        return False


def toggle_mute() -> bool:
    """Toggle mute state."""
    try:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], check=True)
        print("✅ Toggled mute")
        return True
    except Exception as e:
        print(f"❌ Mute toggle error: {e}")
        return False


# ============== WINDOW MANAGEMENT ==============

def maximize_window() -> bool:
    """Maximize the active window."""
    try:
        subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"], check=True)
        print("✅ Window maximized")
        return True
    except FileNotFoundError:
        print("❌ wmctrl not found - install with: sudo apt install wmctrl")
        return False
    except Exception as e:
        print(f"❌ Window error: {e}")
        return False


def minimize_window() -> bool:
    """Minimize the active window."""
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowminimize"], check=True)
        print("✅ Window minimized")
        return True
    except Exception as e:
        print(f"❌ Window error: {e}")
        return False


def close_window() -> bool:
    """Close the active window."""
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowclose"], check=True)
        print("✅ Window closed")
        return True
    except Exception as e:
        print(f"❌ Window error: {e}")
        return False


def switch_workspace(number: int) -> bool:
    """Switch to a specific workspace (1-indexed)."""
    try:
        subprocess.run(["wmctrl", "-s", str(number - 1)], check=True)
        print(f"✅ Switched to workspace {number}")
        return True
    except FileNotFoundError:
        print("❌ wmctrl not found")
        return False
    except Exception as e:
        print(f"❌ Workspace error: {e}")
        return False


def move_to_workspace(number: int) -> bool:
    """Move active window to a specific workspace."""
    try:
        subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-t", str(number - 1)], check=True)
        print(f"✅ Moved window to workspace {number}")
        return True
    except Exception as e:
        print(f"❌ Move error: {e}")
        return False


# ============== CLIPBOARD ==============

def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Uses wl-copy on Wayland, xclip on X11."""
    # Try wl-copy first on Wayland
    if is_wayland():
        try:
            process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            process.communicate(text.encode())
            print(f"✅ Copied to clipboard (wl-copy): {text[:50]}...")
            return True
        except FileNotFoundError:
            pass  # Fall through to xclip

    # Fallback to xclip (X11 or XWayland)
    try:
        process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        process.communicate(text.encode())
        print(f"✅ Copied to clipboard (xclip): {text[:50]}...")
        return True
    except FileNotFoundError:
        print("❌ No clipboard tool found. Install wl-clipboard (Wayland) or xclip (X11)")
        return False
    except Exception as e:
        print(f"❌ Clipboard error: {e}")
        return False


def get_clipboard() -> str:
    """Get text from clipboard. Uses wl-paste on Wayland, xclip on X11."""
    # Try wl-paste first on Wayland
    if is_wayland():
        try:
            result = subprocess.run(["wl-paste"], capture_output=True, text=True)
            content = result.stdout.strip()
            print(f"✅ Clipboard content (wl-paste): {content[:50]}...")
            return content
        except FileNotFoundError:
            pass  # Fall through to xclip

    # Fallback to xclip (X11 or XWayland)
    try:
        result = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True)
        content = result.stdout.strip()
        print(f"✅ Clipboard content (xclip): {content[:50]}...")
        return content
    except FileNotFoundError:
        return "No clipboard tool found"
    except Exception as e:
        return f"Error: {e}"


def paste_clipboard() -> bool:
    """Paste clipboard content at cursor."""
    # Try wtype first on Wayland
    if is_wayland():
        try:
            subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], check=True)
            print("✅ Pasted from clipboard (wtype)")
            return True
        except FileNotFoundError:
            pass  # Fall through to xdotool

    # Fallback to xdotool (X11 or XWayland)
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True)
        print("✅ Pasted from clipboard (xdotool)")
        return True
    except FileNotFoundError:
        print("❌ No paste tool found. Install wtype (Wayland) or xdotool (X11)")
        return False
    except Exception as e:
        print(f"❌ Paste error: {e}")
        return False


# ============== SCREENSHOT ==============

def take_screenshot(region: str = "full") -> str:
    """Take a screenshot. Region can be 'full', 'window', or 'selection'."""
    timestamp = subprocess.run(["date", "+%Y%m%d_%H%M%S"], capture_output=True, text=True).stdout.strip()
    filename = os.path.expanduser(f"~/Pictures/screenshot_{timestamp}.png")

    try:
        if region == "window":
            subprocess.run(["gnome-screenshot", "-w", "-f", filename], check=True)
        elif region == "selection":
            subprocess.run(["gnome-screenshot", "-a", "-f", filename], check=True)
        else:
            subprocess.run(["gnome-screenshot", "-f", filename], check=True)

        print(f"✅ Screenshot saved: {filename}")
        return filename
    except FileNotFoundError:
        # Try scrot as fallback
        try:
            if region == "window":
                subprocess.run(["scrot", "-u", filename], check=True)
            elif region == "selection":
                subprocess.run(["scrot", "-s", filename], check=True)
            else:
                subprocess.run(["scrot", filename], check=True)
            print(f"✅ Screenshot saved: {filename}")
            return filename
        except:
            print("❌ No screenshot tool found")
            return ""
    except Exception as e:
        print(f"❌ Screenshot error: {e}")
        return ""


# ============== REMOTE MODE ==============

REMOTE_MODE_FILE = '/tmp/synthia-remote-mode'
DEFAULT_CHAT_ID = 537808338  # Mark's Telegram ID


def enable_remote_mode() -> bool:
    """Enable remote mode - send updates to Telegram."""
    try:
        with open(REMOTE_MODE_FILE, 'w') as f:
            f.write(str(DEFAULT_CHAT_ID))
        print("✅ Remote mode enabled")
        return True
    except Exception as e:
        print(f"❌ Remote mode error: {e}")
        return False


def disable_remote_mode() -> bool:
    """Disable remote mode - back to voice."""
    try:
        if os.path.exists(REMOTE_MODE_FILE):
            os.remove(REMOTE_MODE_FILE)
        print("✅ Remote mode disabled")
        return True
    except Exception as e:
        print(f"❌ Remote mode error: {e}")
        return False


def is_remote_mode() -> bool:
    """Check if remote mode is enabled."""
    return os.path.exists(REMOTE_MODE_FILE)


# ============== SYSTEM CONTROL ==============

def lock_screen() -> bool:
    """Lock the screen."""
    try:
        # Try different lock commands
        for cmd in [
            ["gnome-screensaver-command", "-l"],
            ["loginctl", "lock-session"],
            ["xdg-screensaver", "lock"],
        ]:
            try:
                subprocess.run(cmd, check=True)
                print("✅ Screen locked")
                return True
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        print("❌ No lock command found")
        return False
    except Exception as e:
        print(f"❌ Lock error: {e}")
        return False


def suspend_system() -> bool:
    """Suspend/sleep the system."""
    try:
        subprocess.run(["systemctl", "suspend"], check=True)
        print("✅ System suspended")
        return True
    except Exception as e:
        print(f"❌ Suspend error: {e}")
        return False


# ============== ACTION EXECUTOR ==============

def execute_actions(actions: List[Dict[str, Any]]) -> tuple[list[bool], str | None]:
    """Execute a list of actions and return (success status list, command output if any)."""
    results = []
    command_output = None

    for action in actions:
        action_type = action.get("type", "")

        # App control
        if action_type == "open_app":
            results.append(open_app(action.get("app", "")))

        elif action_type == "open_url":
            results.append(open_url(action.get("url", ""), action.get("browser", "firefox")))

        elif action_type == "close_app":
            results.append(close_app(action.get("app", "")))

        elif action_type == "run_command":
            output = run_command(action.get("command", ""))
            command_output = output
            results.append(bool(output))

        elif action_type == "type_text":
            results.append(type_text(action.get("text", "")))

        # Volume control
        elif action_type == "set_volume":
            results.append(set_volume(action.get("level", 50)))

        elif action_type == "change_volume":
            results.append(change_volume(action.get("delta", 10)))

        elif action_type == "mute":
            results.append(mute(action.get("state", True)))

        elif action_type == "unmute":
            results.append(mute(False))

        elif action_type == "toggle_mute":
            results.append(toggle_mute())

        # Window management
        elif action_type == "maximize_window":
            results.append(maximize_window())

        elif action_type == "minimize_window":
            results.append(minimize_window())

        elif action_type == "close_window":
            results.append(close_window())

        elif action_type == "switch_workspace":
            results.append(switch_workspace(action.get("number", 1)))

        elif action_type == "move_to_workspace":
            results.append(move_to_workspace(action.get("number", 1)))

        # Clipboard
        elif action_type == "copy_to_clipboard":
            results.append(copy_to_clipboard(action.get("text", "")))

        elif action_type == "get_clipboard":
            content = get_clipboard()
            command_output = content
            results.append(bool(content))

        elif action_type == "paste":
            results.append(paste_clipboard())

        # Screenshot
        elif action_type == "screenshot":
            path = take_screenshot(action.get("region", "full"))
            if path:
                command_output = f"Screenshot saved to {path}"
            results.append(bool(path))

        # System control
        elif action_type == "lock_screen":
            results.append(lock_screen())

        elif action_type == "suspend":
            results.append(suspend_system())

        # Remote mode
        elif action_type == "enable_remote":
            results.append(enable_remote_mode())

        elif action_type == "disable_remote":
            results.append(disable_remote_mode())

        else:
            print(f"⚠️  Unknown action type: {action_type}")
            results.append(False)

    return results, command_output
