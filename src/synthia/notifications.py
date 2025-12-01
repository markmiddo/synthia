"""Desktop notifications for Synthia."""

import subprocess


def notify(title: str, message: str, icon: str = "audio-input-microphone", timeout: int = 3000):
    """Show a desktop notification.

    Args:
        title: Notification title
        message: Notification body text
        icon: Icon name (from system icon theme)
        timeout: Duration in milliseconds
    """
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=Synthia",
                f"--icon={icon}",
                f"--expire-time={timeout}",
                title,
                message,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # notify-send not installed
        pass
    except Exception as e:
        print(f"Notification error: {e}")


def notify_ready():
    """Notify that Synthia is ready."""
    notify(
        "Synthia",
        "Ready! Hold Right Ctrl to dictate, Right Alt for assistant.",
        "audio-input-microphone",
    )


def notify_dictation(text: str):
    """Notify with dictation result."""
    # Truncate long text
    display_text = text[:100] + "..." if len(text) > 100 else text
    notify("Dictation", display_text, "document-edit")


def notify_assistant(response: str):
    """Notify with assistant response."""
    display_text = response[:100] + "..." if len(response) > 100 else response
    notify("Assistant", display_text, "user-available")


def notify_error(message: str):
    """Notify of an error."""
    notify("Synthia Error", message, "dialog-error", timeout=5000)
