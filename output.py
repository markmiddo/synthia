"""Text output via xdotool for LinuxVoice."""

import subprocess
import shlex


def type_text(text: str) -> bool:
    """Type text at the current cursor position using xdotool."""
    if not text:
        return False

    try:
        # Use xdotool to type the text
        # --clearmodifiers ensures modifier keys don't interfere
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--", text],
            check=True,
            timeout=10,
        )
        print(f"⌨️  Typed: {text[:50]}{'...' if len(text) > 50 else ''}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ xdotool error: {e}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ xdotool timed out")
        return False
    except FileNotFoundError:
        print("❌ xdotool not found - please install: sudo apt install xdotool")
        return False
