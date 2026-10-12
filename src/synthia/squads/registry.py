"""The shared squad registry: ~/.local/share/synthia/squads/registry.json.

Written only by this module. Atomic (temp file plus os.replace) under an fcntl lock on
registry.lock. Members whose pane is gone from herdr are marked `ended_at` on the next write.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

DEFAULT_ROOT = Path.home() / ".local" / "share" / "synthia" / "squads"
VERSION = 1


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


@dataclass
class Member:
    agent_name: str
    squad: str | None
    job: str | None
    role: str
    title: str
    parent: str | None
    opened_by: str = "synthia"
    started_at: str = ""
    ended_at: str | None = None
    pane_id: str = ""  # filled from the key on load; not stored in the file

    @property
    def live(self) -> bool:
        return self.ended_at is None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("pane_id")
        return data


LivePanes = Callable[[], set[str]]


class Registry:
    def __init__(self, root: Path = DEFAULT_ROOT, live_panes: LivePanes | None = None) -> None:
        self.root = root
        self.path = root / "registry.json"
        self._lock_path = root / "registry.lock"
        self._live_panes = live_panes

    # ---- storage ----

    def _read(self) -> dict[str, Member]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        members = data.get("members") if isinstance(data, dict) else None
        out: dict[str, Member] = {}
        for pane, body in (members or {}).items():
            if not isinstance(body, dict):
                continue
            try:
                out[pane] = Member(
                    agent_name=str(body["agent_name"]),
                    squad=body.get("squad"),
                    job=body.get("job"),
                    role=str(body.get("role", "")),
                    title=str(body.get("title", "")),
                    parent=body.get("parent"),
                    opened_by=str(body.get("opened_by", "synthia")),
                    started_at=str(body.get("started_at", "")),
                    ended_at=body.get("ended_at"),
                    pane_id=pane,
                )
            except KeyError:
                continue
        return out

    def _write(self, members: dict[str, Member]) -> None:
        body = {"version": VERSION, "members": {p: m.to_json() for p, m in members.items()}}
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(body, indent=2))
        os.replace(tmp, self.path)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _prune(self, members: dict[str, Member]) -> None:
        if self._live_panes is None:
            return
        try:
            alive = self._live_panes()
        except Exception:
            return  # herdr unreachable: leave everything as it is
        stamp = now_iso()
        for pane, m in members.items():
            if m.live and pane not in alive:
                m.ended_at = stamp

    def _mutate(self, fn: Callable[[dict[str, Member]], Any]) -> Any:
        with self._locked():
            members = self._read()
            self._prune(members)
            result = fn(members)
            self._write(members)
            return result

    # ---- API ----

    def add(self, pane_id: str, member: Member) -> None:
        member.pane_id = pane_id
        member.started_at = member.started_at or now_iso()

        def go(members: dict[str, Member]) -> None:
            members[pane_id] = member

        self._mutate(go)

    def end(self, pane_id: str) -> None:
        def go(members: dict[str, Member]) -> None:
            m = members.get(pane_id)
            if m is not None and m.live:
                m.ended_at = now_iso()

        self._mutate(go)

    def prune(self) -> None:
        self._mutate(lambda members: None)

    def members(self) -> dict[str, Member]:
        return self._read()

    def get(self, pane_id: str) -> Member | None:
        return self._read().get(pane_id)

    def live(self, job: str | None = None) -> list[Member]:
        return [m for m in self._read().values() if m.live and (job is None or m.job == job)]

    def find_live(self, name: str) -> Member | None:
        for m in self._read().values():
            if m.live and m.agent_name == name:
                return m
        return None
