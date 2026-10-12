#!/usr/bin/env python3
"""Claude Code PostToolUse hook: log every memory a session reads or writes.

Reads the hook JSON on stdin. When the tool is Read, Write or Edit and the file is a Claude Code
project memory (``~/.claude/projects/<project>/memory/<file>.md``, not ``MEMORY.md``), appends one JSON
line to ``~/.local/share/synthia/brain/recalls.jsonl``. The Synthia HUD turns those lines into pulses
on the hive and a "recalled today" timeline.

This hook must never get in the way: it prints nothing, always exits 0, swallows every error and
imports nothing heavy so it finishes in a few milliseconds.

Register it in ``~/.claude/settings.json`` under ``hooks.PostToolUse`` with matcher ``Read|Write|Edit``.
"""

import json
import os
import sys
from datetime import datetime, timezone

MAX_LOG_BYTES = 5 * 1024 * 1024
TOOL_KINDS = {"Read": "read", "Write": "write", "Edit": "write"}


def default_log_path(home: str) -> str:
    return os.path.join(home, ".local", "share", "synthia", "brain", "recalls.jsonl")


def memory_file(file_path: str, home: str) -> bool:
    """True for ``<home>/.claude/projects/<project>/memory/<name>.md`` other than MEMORY.md."""
    if not isinstance(file_path, str) or not file_path.endswith(".md"):
        return False
    root = os.path.join(home, ".claude", "projects") + os.sep
    path = os.path.normpath(file_path)
    if not path.startswith(root):
        return False
    parts = path[len(root) :].split(os.sep)
    return len(parts) == 3 and parts[1] == "memory" and parts[2] != "MEMORY.md"


def title_of(path: str) -> str:
    """The frontmatter ``name`` of a memory file, else its filename without the extension."""
    fallback = os.path.basename(path)[: -len(".md")]
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(2048)
    except OSError:
        return fallback
    if head.startswith("---"):
        for line in head.splitlines()[1:]:
            if line.strip() == "---":
                break
            if line.startswith("name:"):
                name = line[len("name:") :].strip().strip("\"'")
                if name:
                    return name
    return fallback


def rotate(log_path: str, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Keep the log under ``max_bytes``: move it to ``<log>.1`` (replacing any older one)."""
    try:
        if os.path.getsize(log_path) > max_bytes:
            os.replace(log_path, log_path + ".1")
    except OSError:
        pass


def log_recall(
    payload: dict,
    home: str | None = None,
    log_path: str | None = None,
    now: datetime | None = None,
    pane: str | None = None,
) -> bool:
    """Append a recall line for ``payload`` if it is a memory read or write. Returns whether it did."""
    home = home or os.path.expanduser("~")
    kind = TOOL_KINDS.get(str(payload.get("tool_name")))
    tool_input = payload.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if kind is None or not isinstance(file_path, str) or not memory_file(file_path, home):
        return False
    log_path = log_path or default_log_path(home)
    entry = {
        "at": (now or datetime.now(timezone.utc))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "kind": kind,
        "file": os.path.normpath(file_path),
        "title": title_of(file_path),
        "cwd": payload.get("cwd") or "",
        "session_id": payload.get("session_id") or "",
        "pane": pane if pane is not None else (os.environ.get("HERDR_PANE_ID") or None),
    }
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    rotate(log_path)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            log_recall(payload)
    except Exception:
        pass  # never block a tool call
    return 0


if __name__ == "__main__":
    sys.exit(main())
