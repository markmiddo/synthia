"""Clipboard monitoring for Synthia - tracks clipboard history."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from synthia.display import is_wayland

logger = logging.getLogger(__name__)


class ClipboardMonitor:
    """Monitors system clipboard and maintains history of copied items."""

    def __init__(
        self,
        max_items: int = 5,
        history_file: Optional[str] = None,
    ) -> None:
        self.max_items = max_items
        self.history_file = history_file or os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "synthia-clipboard.json"
        )
        self.history: list[dict] = []
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._last_hash: Optional[str] = None
        self._load_history()

    def _load_history(self) -> None:
        """Load existing history from file."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file) as f:
                    self.history = json.load(f)
        except Exception as e:
            logger.debug("Could not load clipboard history: %s", e)
            self.history = []

    def _save_history(self) -> None:
        """Save history to file with restrictive permissions."""
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)
            # SECURITY: Clipboard may contain sensitive data (passwords, tokens)
            os.chmod(self.history_file, 0o600)
        except Exception as e:
            logger.warning("Failed to save clipboard history: %s", e)

    def _content_hash(self, content: str) -> str:
        """Generate hash of content for deduplication."""
        return hashlib.sha256(content.encode()).hexdigest()

    def _add_item(self, content: str) -> None:
        """Add item to history (deduplicated)."""
        if not content or not content.strip():
            return

        content = content.strip()
        content_hash = self._content_hash(content)

        # Skip if same as last item
        if content_hash == self._last_hash:
            return

        self._last_hash = content_hash

        # Remove duplicate if exists
        self.history = [h for h in self.history if h.get("hash") != content_hash]

        # Add new item at beginning
        item = {
            "id": int(time.time() * 1000),
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "hash": content_hash,
        }
        self.history.insert(0, item)

        # Trim to max items
        self.history = self.history[: self.max_items]

        self._save_history()
        logger.debug("Clipboard captured: %s...", content[:50])

    def _get_clipboard_content(self) -> Optional[str]:
        """Get current clipboard content."""
        try:
            if is_wayland():
                result = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            if result.returncode == 0:
                return result.stdout
        except Exception as e:
            logger.debug("Clipboard read failed: %s", e)
        return None

    def _run_wayland_monitor(self) -> None:
        """Run wl-paste --watch for efficient Wayland monitoring."""
        while self.running:
            try:
                # wl-paste --watch runs a command each time clipboard changes
                # We use cat to just get the content
                self._process = subprocess.Popen(
                    ["wl-paste", "--watch", "cat"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )

                while self.running and self._process.poll() is None:
                    if self._process.stdout is None:
                        break
                    line = self._process.stdout.readline()
                    if line:
                        # Accumulate content until we get empty line
                        content = line.rstrip("\n")
                        self._add_item(content)

            except Exception as e:
                logger.warning("Wayland clipboard monitor error: %s", e)
                time.sleep(1)

    def _run_x11_monitor(self) -> None:
        """Run polling-based monitor for X11."""
        while self.running:
            try:
                content = self._get_clipboard_content()
                if content:
                    self._add_item(content)
                time.sleep(0.5)  # Poll every 500ms
            except Exception as e:
                logger.warning("X11 clipboard monitor error: %s", e)
                time.sleep(1)

    def start(self) -> None:
        """Start the clipboard monitor."""
        if self.running:
            return

        self.running = True

        if is_wayland():
            logger.info("Starting Wayland clipboard monitor (wl-paste --watch)")
            self._thread = threading.Thread(target=self._run_wayland_monitor, daemon=True)
        else:
            logger.info("Starting X11 clipboard monitor (polling)")
            self._thread = threading.Thread(target=self._run_x11_monitor, daemon=True)

        self._thread.start()

    def stop(self) -> None:
        """Stop the clipboard monitor."""
        self.running = False

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1)
            except Exception:
                self._process.kill()
            self._process = None

        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def get_history(self) -> list[dict]:
        """Get current clipboard history."""
        return self.history.copy()

    def copy_item(self, item_id: int) -> bool:
        """Copy a history item back to clipboard."""
        for item in self.history:
            if item.get("id") == item_id:
                return self._copy_to_clipboard(item.get("content", ""))
        return False

    def _copy_to_clipboard(self, content: str) -> bool:
        """Copy content to system clipboard."""
        try:
            if is_wayland():
                process = subprocess.Popen(
                    ["wl-copy"],
                    stdin=subprocess.PIPE,
                    text=True,
                )
                process.communicate(input=content)
            else:
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                    text=True,
                )
                process.communicate(input=content)
            return True
        except Exception as e:
            logger.warning("Failed to copy to clipboard: %s", e)
            return False
