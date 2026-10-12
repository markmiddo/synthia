"""Spoken acknowledgements ("On it, Mark.") rendered once and replayed instantly.

The brain takes several seconds to start answering, so DeskVoice plays one of these short
lines straight away. They are rendered once with the configured Google voice into
~/.cache/synthia/acks/<voice>/ so playback never waits on a synthesis round-trip; a
different voice (or speaking rate) gets its own folder and is rendered on first use.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

ACK_LINES: tuple[str, ...] = (
    "On it, Mark.",
    "No worries, Mark, let me look into that.",
    "Give me a sec.",
    "Sure, checking now.",
)


def default_cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "synthia" / "acks"


class AckBank:
    """A rotating set of pre-rendered acknowledgement files for one voice."""

    def __init__(
        self,
        voice: str,
        render: Callable[[str, str], bool],
        speed: float = 1.0,
        lines: tuple[str, ...] = ACK_LINES,
        cache_root: Path | None = None,
    ) -> None:
        self.voice = voice
        self._render = render
        self._speed = speed
        self._lines = lines
        safe_voice = "".join(c if c.isalnum() or c in "-_." else "_" for c in voice) or "default"
        self.dir = (cache_root or default_cache_root()) / safe_voice
        self._next = 0
        self._lock = threading.Lock()

    def _path(self, line: str) -> Path:
        key = hashlib.sha1(f"{line}|{self._speed}".encode()).hexdigest()[:12]
        return self.dir / f"{key}.mp3"

    def prepare(self) -> int:
        """Render whatever is missing and drop files for lines that no longer exist."""
        self.dir.mkdir(parents=True, exist_ok=True)
        wanted = {self._path(line): line for line in self._lines}
        for stale in self.dir.glob("*.mp3"):
            if stale not in wanted:
                stale.unlink(missing_ok=True)
        made = 0
        for path, line in wanted.items():
            if path.exists():
                continue
            if self._render(line, str(path)):
                made += 1
        return made

    def start(self) -> threading.Thread:
        """Prepare in the background so startup is not held up by synthesis."""

        def run() -> None:
            try:
                made = self.prepare()
                logger.info("acks ready for %s (%d rendered)", self.voice, made)
            except Exception:
                logger.exception("could not prepare acknowledgements")

        t = threading.Thread(target=run, name="ack-prepare", daemon=True)
        t.start()
        return t

    def next(self) -> str | None:
        """The next ready file in rotation, or None if none has been rendered yet."""
        with self._lock:
            for _ in range(len(self._lines)):
                path = self._path(self._lines[self._next % len(self._lines)])
                self._next += 1
                if path.exists():
                    return str(path)
        return None
