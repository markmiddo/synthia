"""Command execution for Synthia assistant."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from typing import Any, Callable

from synthia.display import is_wayland

logger = logging.getLogger(__name__)
from synthia.output import type_text
from synthia.web_search import web_search

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
    """Launch an application.

    SECURITY: Only allows apps in APP_ALIASES or FLATPAK_APPS to prevent
    arbitrary command execution from LLM output.
    """
    app_cmd = _resolve_app_name(app)

    # SECURITY: Only allow known apps to prevent arbitrary command execution
    allowed_apps = set(APP_ALIASES.values()) | set(FLATPAK_APPS.keys())
    if app_cmd not in allowed_apps:
        logger.warning("App not in allowlist: %s", app_cmd)
        return False

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
            logger.info("Opened (Flatpak): %s", flatpak_id)
            return True
        except Exception as e:
            logger.error("Error opening Flatpak %s: %s", flatpak_id, e)
            return False

    # Try regular command
    try:
        subprocess.Popen(
            [app_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Opened: %s", app_cmd)
        return True
    except FileNotFoundError:
        logger.warning("App not found: %s", app_cmd)
        return False
    except Exception as e:
        logger.error("Error opening %s: %s", app_cmd, e)
        return False


def open_url(url: str, browser: str = "google-chrome") -> bool:
    """Open a URL in Chrome (Flatpak).

    SECURITY: Only allows http/https URLs to prevent javascript:, file:,
    data:, or other dangerous URI schemes.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # SECURITY: Reject non-http(s) schemes that could have been prepended
    if not url.startswith(("http://", "https://")):
        logger.warning("Invalid URL scheme: %s", url)
        return False

    # Use Chrome Flatpak
    try:
        subprocess.Popen(
            ["flatpak", "run", "com.google.Chrome", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Opened URL in Chrome: %s", url)
        return True
    except Exception as e:
        logger.error("Error opening URL: %s", e)
        return False


def close_app(app: str) -> bool:
    """Close an application by name.

    SECURITY: Only allows closing apps in APP_ALIASES or FLATPAK_APPS to prevent
    pkill -f from matching unintended processes via LLM-crafted input.
    """
    app_cmd = _resolve_app_name(app)

    # SECURITY: Only allow closing known apps
    allowed_apps = set(APP_ALIASES.values()) | set(FLATPAK_APPS.keys())
    if app_cmd not in allowed_apps:
        logger.warning("Cannot close unknown app: %s", app_cmd)
        return False

    try:
        subprocess.run(["pkill", "-f", app_cmd], check=False)
        logger.info("Closed: %s", app_cmd)
        return True
    except Exception as e:
        logger.error("Error closing %s: %s", app_cmd, e)
        return False


# Allowlist of safe commands that can be executed
# SECURITY: Only include commands that cannot exfiltrate data or modify the system.
# Excluded: curl/wget (can exfiltrate data or download payloads),
#           cat/head/tail (can read sensitive files like ~/.ssh/id_rsa),
#           find (can enumerate filesystem), echo (can write via redirection)
SAFE_COMMANDS = {
    # System info (read-only, no file access)
    "date",
    "uptime",
    "whoami",
    "hostname",
    "uname",
    "free",
    "df",
    "ps",
    # Network info (read-only)
    "ip",
    "ifconfig",
    "ping",
    # File listing (directory only, not file contents)
    "ls",
    "pwd",
    "wc",
    "which",
    # System utilities
    "cal",
    "bc",
}

# Dangerous patterns that should never be allowed
DANGEROUS_PATTERNS = [
    "rm ",
    "rm\t",
    "rmdir",
    "mkfs",
    "dd ",
    "dd\t",
    "> /",
    ">/",
    ">> /",
    ">>/",  # Redirecting to system paths
    "sudo",
    "su ",
    "su\t",
    "chmod",
    "chown",
    "chgrp",
    "|sh",
    "| sh",
    "|bash",
    "| bash",
    "|zsh",
    "| zsh",
    "$(",
    "`",  # Command substitution
    "eval ",
    "exec ",
    "/etc/",
    "/usr/",
    "/bin/",
    "/sbin/",
    "/var/",
    "/root/",
    "passwd",
    "shadow",
    "curl|",
    "wget|",
    "curl |",
    "wget |",  # Piping downloads to shell
]


def run_command(command: str) -> str:
    """Run a shell command and return output.

    SECURITY: Only allows commands from SAFE_COMMANDS allowlist.
    Blocks dangerous patterns to prevent command injection.
    """
    if not command or not command.strip():
        return "No command provided"

    command = command.strip()

    # Check for dangerous patterns
    command_lower = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in command_lower:
            logger.warning("Blocked dangerous command pattern: %s", pattern)
            return f"Command blocked for security: contains '{pattern}'"

    # Extract the base command (first word)
    base_cmd = command.split()[0].split("/")[-1]  # Handle full paths

    # Check if base command is in allowlist
    if base_cmd not in SAFE_COMMANDS:
        logger.warning("Command not in allowlist: %s", base_cmd)
        return f"Command '{base_cmd}' is not allowed. Allowed commands: {', '.join(sorted(SAFE_COMMANDS))}"

    try:
        # Use shell=False with shlex for safer execution
        args = shlex.split(command)

        result = subprocess.run(
            args,
            shell=False,  # SECURITY: Never use shell=True
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr
        logger.info("Command output: %s...", output[:100])
        return output.strip()
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out")
        return "Command timed out"
    except Exception as e:
        logger.error("Command error: %s", e)
        return str(e)


# ============== VOLUME CONTROL ==============


def set_volume(level: int) -> bool:
    """Set system volume to a percentage (0-100)."""
    level = max(0, min(100, level))
    try:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"], check=True)
        logger.info("Volume set to %d%%", level)
        return True
    except Exception as e:
        logger.error("Volume error: %s", e)
        return False


def change_volume(delta: int) -> bool:
    """Change volume by delta percentage (positive or negative)."""
    sign = "+" if delta >= 0 else ""
    try:
        subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{delta}%"], check=True
        )
        logger.info("Volume changed by %s%d%%", sign, delta)
        return True
    except Exception as e:
        logger.error("Volume error: %s", e)
        return False


def mute(state: bool = True) -> bool:
    """Mute or unmute system audio."""
    try:
        value = "1" if state else "0"
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", value], check=True)
        logger.info("Muted" if state else "Unmuted")
        return True
    except Exception as e:
        logger.error("Mute error: %s", e)
        return False


def toggle_mute() -> bool:
    """Toggle mute state."""
    try:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], check=True)
        logger.info("Toggled mute")
        return True
    except Exception as e:
        logger.error("Mute toggle error: %s", e)
        return False


# ============== WINDOW MANAGEMENT ==============


def maximize_window() -> bool:
    """Maximize the active window."""
    if is_wayland():
        # On Wayland, use keyboard shortcut (works on most compositors including Cosmic)
        try:
            subprocess.run(["wtype", "-M", "logo", "-k", "Up", "-m", "logo"], check=True)
            logger.info("Window maximized (Wayland)")
            return True
        except FileNotFoundError:
            logger.warning("wtype not found - install with: sudo apt install wtype")
            return False
        except Exception as e:
            logger.error("Window error: %s", e)
            return False
    else:
        try:
            subprocess.run(
                ["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"], check=True
            )
            logger.info("Window maximized")
            return True
        except FileNotFoundError:
            logger.warning("wmctrl not found - install with: sudo apt install wmctrl")
            return False
        except Exception as e:
            logger.error("Window error: %s", e)
            return False


def minimize_window() -> bool:
    """Minimize the active window."""
    if is_wayland():
        # On Wayland, use keyboard shortcut
        try:
            subprocess.run(["wtype", "-M", "logo", "-k", "h", "-m", "logo"], check=True)
            logger.info("Window minimized (Wayland)")
            return True
        except FileNotFoundError:
            logger.warning("wtype not found")
            return False
        except Exception as e:
            logger.error("Window error: %s", e)
            return False
    else:
        try:
            subprocess.run(["xdotool", "getactivewindow", "windowminimize"], check=True)
            logger.info("Window minimized")
            return True
        except Exception as e:
            logger.error("Window error: %s", e)
            return False


def close_window() -> bool:
    """Close the active window."""
    if is_wayland():
        # On Wayland, use keyboard shortcut (Alt+F4 is universal)
        try:
            subprocess.run(["wtype", "-M", "alt", "-k", "F4", "-m", "alt"], check=True)
            logger.info("Window closed (Wayland)")
            return True
        except FileNotFoundError:
            logger.warning("wtype not found")
            return False
        except Exception as e:
            logger.error("Window error: %s", e)
            return False
    else:
        try:
            subprocess.run(["xdotool", "getactivewindow", "windowclose"], check=True)
            logger.info("Window closed")
            return True
        except Exception as e:
            logger.error("Window error: %s", e)
            return False


def switch_workspace(number: int) -> bool:
    """Switch to a specific workspace (1-indexed)."""
    if is_wayland():
        # On Cosmic/Wayland, use Super+number
        try:
            subprocess.run(["wtype", "-M", "logo", "-k", str(number), "-m", "logo"], check=True)
            logger.info("Switched to workspace %d (Wayland)", number)
            return True
        except FileNotFoundError:
            logger.warning("wtype not found")
            return False
        except Exception as e:
            logger.error("Workspace error: %s", e)
            return False
    else:
        try:
            subprocess.run(["wmctrl", "-s", str(number - 1)], check=True)
            logger.info("Switched to workspace %d", number)
            return True
        except FileNotFoundError:
            logger.warning("wmctrl not found")
            return False
        except Exception as e:
            logger.error("Workspace error: %s", e)
            return False


def move_to_workspace(number: int) -> bool:
    """Move active window to a specific workspace."""
    if is_wayland():
        # On Cosmic/Wayland, use Super+Shift+number
        try:
            subprocess.run(
                [
                    "wtype",
                    "-M",
                    "logo",
                    "-M",
                    "shift",
                    "-k",
                    str(number),
                    "-m",
                    "shift",
                    "-m",
                    "logo",
                ],
                check=True,
            )
            logger.info("Moved window to workspace %d (Wayland)", number)
            return True
        except FileNotFoundError:
            logger.warning("wtype not found")
            return False
        except Exception as e:
            logger.error("Move error: %s", e)
            return False
    else:
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-t", str(number - 1)], check=True)
            logger.info("Moved window to workspace %d", number)
            return True
        except Exception as e:
            logger.error("Move error: %s", e)
            return False


# ============== CLIPBOARD ==============


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Uses wl-copy on Wayland, xclip on X11."""
    # Try wl-copy first on Wayland
    if is_wayland():
        try:
            process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            process.communicate(text.encode())
            logger.info("Copied to clipboard (wl-copy): %s...", text[:50])
            return True
        except FileNotFoundError:
            pass  # Fall through to xclip

    # Fallback to xclip (X11 or XWayland)
    try:
        process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        process.communicate(text.encode())
        logger.info("Copied to clipboard (xclip): %s...", text[:50])
        return True
    except FileNotFoundError:
        logger.warning("No clipboard tool found. Install wl-clipboard (Wayland) or xclip (X11)")
        return False
    except Exception as e:
        logger.error("Clipboard error: %s", e)
        return False


def get_clipboard() -> str:
    """Get text from clipboard. Uses wl-paste on Wayland, xclip on X11."""
    # Try wl-paste first on Wayland
    if is_wayland():
        try:
            result = subprocess.run(["wl-paste"], capture_output=True, text=True)
            content = result.stdout.strip()
            logger.info("Clipboard content (wl-paste): %s...", content[:50])
            return content
        except FileNotFoundError:
            pass  # Fall through to xclip

    # Fallback to xclip (X11 or XWayland)
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True
        )
        content = result.stdout.strip()
        logger.info("Clipboard content (xclip): %s...", content[:50])
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
            logger.info("Pasted from clipboard (wtype)")
            return True
        except FileNotFoundError:
            pass  # Fall through to xdotool

    # Fallback to xdotool (X11 or XWayland)
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True)
        logger.info("Pasted from clipboard (xdotool)")
        return True
    except FileNotFoundError:
        logger.warning("No paste tool found. Install wtype (Wayland) or xdotool (X11)")
        return False
    except Exception as e:
        logger.error("Paste error: %s", e)
        return False


# ============== SCREENSHOT ==============


def take_screenshot(region: str = "full") -> str:
    """Take a screenshot. Region can be 'full', 'window', or 'selection'."""
    timestamp = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"], capture_output=True, text=True
    ).stdout.strip()
    filename = os.path.expanduser(f"~/Pictures/screenshot_{timestamp}.png")

    try:
        if region == "window":
            subprocess.run(["gnome-screenshot", "-w", "-f", filename], check=True)
        elif region == "selection":
            subprocess.run(["gnome-screenshot", "-a", "-f", filename], check=True)
        else:
            subprocess.run(["gnome-screenshot", "-f", filename], check=True)

        logger.info("Screenshot saved: %s", filename)
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
            logger.info("Screenshot saved: %s", filename)
            return filename
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning("No screenshot tool found")
            return ""
    except subprocess.CalledProcessError as e:
        logger.error("Screenshot error: %s", e)
        return ""


# ============== REMOTE MODE ==============

# Use XDG_RUNTIME_DIR for secure temp file (user-only access)
REMOTE_MODE_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "synthia-remote-mode")


def _get_telegram_chat_id() -> int:
    """Get Telegram chat ID from config file."""
    from synthia.config import load_config

    config = load_config()
    allowed_users = config.get("telegram_allowed_users", [])
    if allowed_users:
        return int(allowed_users[0])  # Use first allowed user as default
    return 0


def enable_remote_mode() -> bool:
    """Enable remote mode - send updates to Telegram."""
    chat_id = _get_telegram_chat_id()
    if not chat_id:
        logger.error("Remote mode error: No telegram_allowed_users configured in config.yaml")
        return False

    try:
        with open(REMOTE_MODE_FILE, "w") as f:
            f.write(str(chat_id))
        # Set restrictive permissions (owner read/write only)
        os.chmod(REMOTE_MODE_FILE, 0o600)
        logger.info("Remote mode enabled")
        return True
    except Exception as e:
        logger.error("Remote mode error: %s", e)
        return False


def disable_remote_mode() -> bool:
    """Disable remote mode - back to voice."""
    try:
        if os.path.exists(REMOTE_MODE_FILE):
            os.remove(REMOTE_MODE_FILE)
        logger.info("Remote mode disabled")
        return True
    except Exception as e:
        logger.error("Remote mode error: %s", e)
        return False


def is_remote_mode() -> bool:
    """Check if remote mode is enabled."""
    return os.path.exists(REMOTE_MODE_FILE)


# ============== MEMORY SYSTEM ==============


def memory_recall(tags: list[str]) -> str:
    """Recall memories by tags and return formatted output."""
    from synthia.memory import get_memory_system

    entries = get_memory_system().recall(tags, limit=5)

    if not entries:
        return f"No memories found for tags: {', '.join(tags)}"

    lines = [f"Found {len(entries)} relevant memories:"]
    for entry in entries:
        lines.append(entry.format_display())

    return "\n".join(lines)


def memory_search(query: str) -> str:
    """Search memories by text and return formatted output."""
    from synthia.memory import get_memory_system

    entries = get_memory_system().search_text(query, limit=5)

    if not entries:
        return f"No memories found matching: {query}"

    lines = [f"Found {len(entries)} matching memories:"]
    for entry in entries:
        lines.append(entry.format_display())

    return "\n".join(lines)


def memory_add(category: str, tags: list[str], **data: Any) -> bool:
    """Add a new memory entry."""
    from synthia.memory import remember

    return remember(category, tags, **data)


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
                logger.info("Screen locked")
                return True
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        logger.warning("No lock command found")
        return False
    except Exception as e:
        logger.error("Lock error: %s", e)
        return False


def suspend_system() -> bool:
    """Suspend/sleep the system."""
    try:
        subprocess.run(["systemctl", "suspend"], check=True)
        logger.info("System suspended")
        return True
    except Exception as e:
        logger.error("Suspend error: %s", e)
        return False


# ============== ACTION EXECUTOR ==============

# Action dispatch table - maps action types to handler functions
_ACTION_HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    # App control
    "open_app": lambda a: open_app(a.get("app", "")),
    "open_url": lambda a: open_url(a.get("url", ""), a.get("browser", "firefox")),
    "close_app": lambda a: close_app(a.get("app", "")),
    "type_text": lambda a: type_text(a.get("text", "")),
    # Volume control
    "set_volume": lambda a: set_volume(a.get("level", 50)),
    "change_volume": lambda a: change_volume(a.get("delta", 10)),
    "mute": lambda a: mute(a.get("state", True)),
    "unmute": lambda a: mute(False),
    "toggle_mute": lambda a: toggle_mute(),
    # Window management
    "maximize_window": lambda a: maximize_window(),
    "minimize_window": lambda a: minimize_window(),
    "close_window": lambda a: close_window(),
    "switch_workspace": lambda a: switch_workspace(a.get("number", 1)),
    "move_to_workspace": lambda a: move_to_workspace(a.get("number", 1)),
    # Clipboard
    "copy_to_clipboard": lambda a: copy_to_clipboard(a.get("text", "")),
    "paste": lambda a: paste_clipboard(),
    # System control
    "lock_screen": lambda a: lock_screen(),
    "suspend": lambda a: suspend_system(),
    # Remote mode
    "enable_remote": lambda a: enable_remote_mode(),
    "disable_remote": lambda a: disable_remote_mode(),
}


def execute_actions(actions: list[dict[str, Any]]) -> tuple[list[bool], str | None]:
    """Execute a list of actions and return (success status list, command output if any)."""
    results: list[bool] = []
    command_output: str | None = None

    for action in actions:
        action_type = action.get("type", "")

        # Special handlers that return output
        if action_type == "run_command":
            output = run_command(action.get("command", ""))
            command_output = output
            results.append(bool(output))

        elif action_type == "get_clipboard":
            content = get_clipboard()
            command_output = content
            results.append(bool(content))

        elif action_type == "screenshot":
            path = take_screenshot(action.get("region", "full"))
            if path:
                command_output = f"Screenshot saved to {path}"
            results.append(bool(path))

        elif action_type == "web_search":
            query = action.get("query", "")
            if query:
                answer = web_search(query)
                command_output = answer
                results.append(bool(answer))
            else:
                results.append(False)

        elif action_type == "memory_recall":
            tags = action.get("tags", [])
            if tags:
                output = memory_recall(tags)
                command_output = output
                results.append(True)
            else:
                results.append(False)

        elif action_type == "memory_search":
            query = action.get("query", "")
            if query:
                output = memory_search(query)
                command_output = output
                results.append(True)
            else:
                results.append(False)

        elif action_type == "memory_add":
            category = action.get("category", "")
            tags = action.get("tags", [])
            data = action.get("data", {})
            if category and tags and data:
                success = memory_add(category, tags, **data)
                if success:
                    command_output = f"Memory saved to {category}"
                results.append(success)
            else:
                results.append(False)

        # Standard handlers from dispatch table
        elif action_type in _ACTION_HANDLERS:
            results.append(_ACTION_HANDLERS[action_type](action))

        else:
            logger.warning("Unknown action type: %s", action_type)
            results.append(False)

    return results, command_output
