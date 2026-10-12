"""Tail ~/.local/share/synthia/squads/events.jsonl for the brain.

Robust to a missing file, truncation and replacement. The offset (and the file's inode) is
persisted so a restart neither repeats nor drops events.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class EventTail:
    def __init__(self, path: Path, offset_file: Path) -> None:
        self.path = path
        self.offset_file = offset_file

    def _load(self) -> tuple[int, int | None]:
        try:
            data = json.loads(self.offset_file.read_text())
            return max(0, int(data["offset"])), data.get("inode")
        except (OSError, ValueError, KeyError, TypeError):
            return 0, None

    def _save(self, offset: int, inode: int | None) -> None:
        try:
            self.offset_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.offset_file.with_name(self.offset_file.name + ".tmp")
            tmp.write_text(json.dumps({"offset": offset, "inode": inode}))
            os.replace(tmp, self.offset_file)
        except OSError:
            pass  # a read-only state dir must not stop the brain

    def poll(self) -> list[dict[str, Any]]:
        """New complete events since the last poll."""
        offset, saved_inode = self._load()
        try:
            st = self.path.stat()
        except OSError:
            if offset:
                self._save(0, None)
            return []
        if st.st_size < offset or (saved_inode is not None and saved_inode != st.st_ino):
            offset = 0  # truncated or replaced: start over
        try:
            with open(self.path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except OSError:
            return []
        end = chunk.rfind(b"\n") + 1  # only whole lines; a half-written one waits
        events: list[dict[str, Any]] = []
        for raw in chunk[:end].splitlines():
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if isinstance(ev, dict):
                events.append(ev)
        if end or offset != self._load()[0] or saved_inode != st.st_ino:
            self._save(offset + end, st.st_ino)
        return events
