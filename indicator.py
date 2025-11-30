"""System tray indicator for Synthia."""

import os
import threading
from enum import Enum
from PIL import Image
import pystray
from pystray import MenuItem as Item


class Status(Enum):
    """Status states for the indicator."""
    READY = "ready"
    RECORDING = "recording"
    THINKING = "thinking"
    ASSISTANT = "assistant"


# Map status to icon files
STATUS_ICONS = {
    Status.READY: "mic-ready.png",
    Status.RECORDING: "mic-recording.png",
    Status.THINKING: "mic-thinking.png",
    Status.ASSISTANT: "mic-assistant.png",
}


class TrayIndicator:
    """System tray indicator showing Synthia status."""

    def __init__(self, on_quit=None):
        self.on_quit = on_quit
        self.status = Status.READY
        self.icon = None
        self._thread = None

        # Get the icons directory path
        self._icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    def _get_icon(self) -> Image.Image:
        """Get the icon for current status."""
        icon_file = STATUS_ICONS.get(self.status, "mic-ready.png")
        icon_path = os.path.join(self._icons_dir, icon_file)

        try:
            img = Image.open(icon_path)
            # Resize to standard tray size
            return img.resize((22, 22), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"Icon error: {e}")
            # Fallback to simple colored square
            return self._create_fallback(STATUS_ICONS.get(self.status, "gray"))

    def _create_fallback(self, color_hint: str) -> Image.Image:
        """Create fallback icon if file not found."""
        colors = {
            "mic-ready.png": "#AAAAAA",
            "mic-recording.png": "#EF4444",
            "mic-thinking.png": "#F59E0B",
            "mic-assistant.png": "#3B82F6",
        }
        color = colors.get(color_hint, "#AAAAAA")

        img = Image.new('RGBA', (22, 22), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 20, 20], fill=color)
        return img

    def _create_menu(self):
        """Create the tray icon menu."""
        return pystray.Menu(
            Item("Synthia", None, enabled=False),
            Item("─────────", None, enabled=False),
            Item("Right Ctrl: Dictation", None, enabled=False),
            Item("Right Alt: Assistant", None, enabled=False),
            Item("─────────", None, enabled=False),
            Item("Quit", self._on_quit_clicked),
        )

    def _on_quit_clicked(self, icon, item):
        """Handle quit menu click."""
        self.stop()
        if self.on_quit:
            self.on_quit()

    def set_status(self, status: Status):
        """Update the indicator status."""
        self.status = status
        if self.icon:
            self.icon.icon = self._get_icon()

    def start(self):
        """Start the tray indicator in a background thread."""
        def run():
            self.icon = pystray.Icon(
                "synthia",
                self._get_icon(),
                "Synthia",
                menu=self._create_menu()
            )
            self.icon.run()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the tray indicator."""
        if self.icon:
            self.icon.stop()
