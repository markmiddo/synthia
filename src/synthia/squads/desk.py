"""A job folder per job: brief, status, per-role work folders, finished output."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from synthia.squads.model import SquadError
from synthia.squads.registry import now_iso

STATES = ("briefed", "working", "review", "done", "stopped")


def slugify(text: str, fallback: str = "job") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return slug or fallback


def job_dir(root: Path, squad: str, job: str) -> Path:
    return root / squad / "jobs" / job


def create(root: Path, squad: str, brief: str, slug: str, today: date) -> tuple[str, Path]:
    """Make the desk for a new job; returns (job id, path)."""
    jobs = root / squad / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    base = f"{today.isoformat()}-{slugify(slug)}"
    job, n = base, 1
    while True:
        try:
            (jobs / job).mkdir()
            break
        except FileExistsError:
            n += 1
            job = f"{base}-{n}"
    path = jobs / job
    (path / "work").mkdir()
    (path / "out").mkdir()
    (path / "brief.md").write_text(brief.strip() + "\n")
    write_status(path, {"state": "briefed", "log": []})
    return job, path


def work_dir(path: Path, role: str) -> Path:
    d = path / "work" / role
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_status(path: Path) -> dict[str, Any]:
    try:
        data = json.loads((path / "status.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"state": "briefed", "log": []}
    return data if isinstance(data, dict) else {"state": "briefed", "log": []}


def write_status(path: Path, status: dict[str, Any]) -> None:
    tmp = path / f"status.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(status, indent=2))
    os.replace(tmp, path / "status.json")


@contextlib.contextmanager
def locked(path: Path, name: str = "status.lock") -> Iterator[None]:
    with open(path / name, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def log(path: Path, who: str, text: str) -> None:
    with locked(path):
        status = read_status(path)
        status.setdefault("log", []).append({"at": now_iso(), "who": who, "text": text})
        write_status(path, status)


def set_state(path: Path, state: str, who: str = "synthia", note: str | None = None) -> None:
    if state not in STATES:
        raise SquadError(f"unknown state {state!r}")
    with locked(path):
        status = read_status(path)
        status["state"] = state
        status.setdefault("log", []).append(
            {"at": now_iso(), "who": who, "text": note or f"state: {state}"}
        )
        write_status(path, status)


def deliver(path: Path, source: Path, who: str) -> Path:
    if not source.is_file():
        raise SquadError(f"{source} is not a file")
    dest = path / "out" / source.name
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    log(path, who, f"delivered {source.name}")
    return dest
