"""A compact picture of Mark's live agents, prepended to desk and Telegram turns.

Answering "what's going on?" used to cost the brain several tool calls (read herdr panes,
read transcripts). Building the picture here, once per turn and cached for a few seconds,
lets the model answer from the prompt alone.

Everything is read-only and best effort: any failure yields an empty string so a turn is
never blocked or failed by the fleet reader. The sub-agent logic mirrors
gui/src-tauri/src/commands/fleet.rs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

HERDR_TIMEOUT_S = 1.5
CACHE_TTL_S = 3.0
# A sub-agent whose transcript changed within this window is still working.
SUBAGENT_LIVE_S = 60
SUBAGENT_SCAN_CAP = 200
MAX_LINES = 12  # header line included
MAX_LIVE_NAMES = 2
MAX_NAME_CHARS = 60

CONTEXT_LABEL = "[context, not from Mark]"
MARK_LABEL = "[Mark said]"

# needs-you first, then working, then the quiet ones.
_STATUS_ORDER = {"blocked": 0, "working": 1, "done": 2, "idle": 3}

Snapshotter = Callable[[], Awaitable[str]]


async def run_herdr_snapshot(timeout_s: float = HERDR_TIMEOUT_S) -> str:
    """`herdr api snapshot`, read-only, killed after the timeout."""
    proc = await asyncio.create_subprocess_exec(
        "herdr",
        "api",
        "snapshot",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"herdr snapshot exited {proc.returncode}")
    return out.decode("utf-8", "replace")


def project_dir_name(cwd: str) -> str:
    """Claude names a project directory after the cwd with `/` and `.` replaced by `-`."""
    return "".join("-" if c in "/." else c for c in cwd)


def repo_name(cwd: str, home: Path) -> str:
    """First segment under ~/dev/eventflo/, otherwise the last path segment."""
    path = Path(cwd)
    try:
        rest = path.relative_to(home / "dev" / "eventflo")
        return rest.parts[0] if rest.parts else "eventflo"
    except ValueError:
        return path.name or cwd


def read_subagents(
    projects_root: Path, cwd: str, session: str, now: float
) -> list[tuple[str, bool]]:
    """(description, live) per sub-agent of one Claude session, newest first."""
    if not session or "/" in session or ".." in session:
        return []
    directory = projects_root / project_dir_name(cwd) / session / "subagents"
    try:
        names = [p for p in directory.iterdir() if p.name.endswith(".meta.json")]
    except OSError:
        return []
    found: list[tuple[float, Path, bool]] = []
    for meta in names[:SUBAGENT_SCAN_CAP]:
        transcript = directory / (meta.name[: -len(".meta.json")] + ".jsonl")
        try:
            modified = (transcript if transcript.exists() else meta).stat().st_mtime
        except OSError:
            continue
        found.append((modified, meta, now - modified <= SUBAGENT_LIVE_S))
    found.sort(key=lambda f: f[0], reverse=True)
    out: list[tuple[str, bool]] = []
    for _, meta, live in found:
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            description = str(data.get("description") or "").strip()
        except (OSError, ValueError, AttributeError):
            continue
        out.append((description or "unnamed sub-agent", live))
    return out


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_NAME_CHARS else text[: MAX_NAME_CHARS - 1].rstrip() + "…"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


class FleetContext:
    """Builds and caches the live-agents block."""

    def __init__(
        self,
        snapshot: Snapshotter | None = None,
        projects_root: Path | None = None,
        home: Path | None = None,
        clock: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        ttl_s: float = CACHE_TTL_S,
    ) -> None:
        self._snapshot = snapshot or run_herdr_snapshot
        self._home = home or Path.home()
        self._projects = projects_root or self._home / ".claude" / "projects"
        self._clock = clock
        self._mono = mono
        self._ttl = ttl_s
        self._cached: tuple[float, str] | None = None
        self._lock = asyncio.Lock()
        # pane id -> (herdr status, epoch seconds we first saw it in that status)
        self._since: dict[str, tuple[str, float]] = {}

    async def summary(self) -> str:
        """The block text, or "" on any failure. Never raises."""
        try:
            async with self._lock:
                if self._cached and self._mono() - self._cached[0] < self._ttl:
                    return self._cached[1]
                text = await self._build()
                self._cached = (self._mono(), text)
                return text
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - never fail a turn over context
            log.debug("fleet context unavailable: %s", exc)
            return ""

    async def _build(self) -> str:
        raw = await self._snapshot()
        agents = json.loads(raw)["result"]["snapshot"]["agents"]
        now = self._clock()
        seen: set[str] = set()
        rows: list[tuple[int, int, str]] = []
        for index, agent in enumerate(agents):
            pane = str(agent.get("pane_id") or index)
            status = str(agent.get("agent_status") or "idle")
            seen.add(pane)
            prev = self._since.get(pane)
            if prev is None or prev[0] != status:
                self._since[pane] = (status, now)
            rows.append((_STATUS_ORDER.get(status, 3), index, self._line(agent, status, now)))
        for gone in set(self._since) - seen:
            del self._since[gone]
        if not rows:
            return ""
        rows.sort(key=lambda r: (r[0], r[1]))
        lines = [r[2] for r in rows]
        room = MAX_LINES - 1
        if len(lines) > room:
            extra = len(lines) - (room - 1)
            lines = lines[: room - 1] + [f"plus {extra} more agents"]
        stamp = datetime.fromtimestamp(now).strftime("%H:%M")
        return "\n".join([f"[Live agents at {stamp}]"] + lines)

    def _line(self, agent: dict[str, Any], status: str, now: float) -> str:
        cwd = str(agent.get("cwd") or "")
        kind = str(agent.get("agent") or "agent")
        title = _clip(str(agent.get("terminal_title_stripped") or "")) or kind
        where = repo_name(cwd, self._home) if cwd else kind
        session = ""
        info = agent.get("agent_session")
        if isinstance(info, dict) and kind == "claude":
            session = str(info.get("value") or "")
        word = {"blocked": "NEEDS YOU", "working": "working"}.get(status, status)
        since = self._since.get(str(agent.get("pane_id")))
        age = ""
        if status != "blocked" and since and since[1] < now - 1:
            age = " " + _duration(now - since[1])
        elif status in ("idle", "done"):
            idle = self._transcript_age(cwd, session, now)
            if idle is not None:
                age = " " + _duration(idle)
        line = f"{title} ({where}): {word}{age}"
        subs = read_subagents(self._projects, cwd, session, now) if session else []
        if subs:
            live = [d for d, is_live in subs if is_live]
            done = len(subs) - len(live)
            parts = []
            if live:
                names = "; ".join(_clip(d) for d in live[:MAX_LIVE_NAMES])
                more = len(live) - MAX_LIVE_NAMES
                parts.append(
                    "live sub-agents: " + names + (f" and {more} more" if more > 0 else "")
                )
            if done:
                parts.append(f"{done} done")
            line += "; " + "; ".join(parts)
        return line + "."

    def _transcript_age(self, cwd: str, session: str, now: float) -> float | None:
        if not session or "/" in session or ".." in session:
            return None
        path = self._projects / project_dir_name(cwd) / f"{session}.jsonl"
        try:
            return max(0.0, now - path.stat().st_mtime)
        except OSError:
            return None


def wrap_context(summary: str) -> str:
    """The marked block placed ahead of Mark's words, or "" when there is no summary."""
    if not summary:
        return ""
    return f"{CONTEXT_LABEL} {summary}\n\n{MARK_LABEL} "
