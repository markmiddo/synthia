"""Headless Claude Code workers: dispatch, track, time out, report."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 600


@dataclass
class JobRecord:
    id: str
    name: str
    prompt: str
    started: str
    finished: str | None = None
    ok: bool | None = None
    summary: str = ""
    log_path: str = ""
    pid: int | None = None
    status: str = "queued"
    delivered: bool = False


@dataclass
class JobFinished:
    job: JobRecord


Runner = Callable[[JobRecord], Awaitable[tuple[int, str, str]]]


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def summarize(stdout: str, limit: int = SUMMARY_LIMIT) -> tuple[bool, str]:
    """Parse `claude -p --output-format json` stdout into (ok, summary)."""
    try:
        data = json.loads(stdout.strip().splitlines()[-1] if stdout.strip() else "")
    except (json.JSONDecodeError, IndexError):
        return False, stdout.strip()[:limit]
    if not isinstance(data, dict):
        return False, stdout.strip()[:limit]
    ok = not bool(data.get("is_error"))
    text = str(data.get("result") or "").strip()
    return ok, text[:limit]


class JobStore:
    """One JSON file per job under root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def save(self, record: JobRecord) -> None:
        self._path(record.id).write_text(json.dumps(asdict(record), indent=2))

    def load(self, job_id: str) -> JobRecord | None:
        p = self._path(job_id)
        if not p.exists():
            return None
        return JobRecord(**json.loads(p.read_text()))

    def list_all(self) -> list[JobRecord]:
        records = [JobRecord(**json.loads(p.read_text())) for p in self.root.glob("*.json")]
        return sorted(records, key=lambda r: r.started)

    def undelivered(self) -> list[JobRecord]:
        return [
            r
            for r in self.list_all()
            if r.status in ("done", "failed", "cancelled") and not r.delivered
        ]


class JobManager:
    def __init__(
        self,
        store: JobStore,
        events: asyncio.Queue[JobFinished],
        runner: Runner,
        max_workers: int = 2,
        timeout_s: float = 1800,
    ) -> None:
        self.store = store
        self.events = events
        self.runner = runner
        self.timeout_s = timeout_s
        self._sem = asyncio.Semaphore(max_workers)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._records: dict[str, JobRecord] = {}

    async def dispatch(self, name: str, prompt: str) -> JobRecord:
        rec = JobRecord(id=uuid.uuid4().hex[:8], name=name, prompt=prompt, started=_now())
        rec.log_path = str(self.store.root / f"{rec.id}.log")
        self._records[rec.id] = rec
        self.store.save(rec)
        self._tasks[rec.id] = asyncio.create_task(self._run(rec))
        return rec

    def status(self, job_id: str) -> JobRecord | None:
        return self._records.get(job_id) or self.store.load(job_id)

    def list_jobs(self) -> list[JobRecord]:
        return sorted(self._records.values(), key=lambda r: r.started)

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        rec = self._records.get(job_id)
        if task is None or rec is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def shutdown(self) -> None:
        for job_id in list(self._tasks):
            await self.cancel(job_id)

    async def _run(self, rec: JobRecord) -> None:
        try:
            async with self._sem:
                rec.status = "running"
                self.store.save(rec)
                try:
                    code, out, err = await asyncio.wait_for(self.runner(rec), self.timeout_s)
                except asyncio.TimeoutError:
                    self._finish(rec, "failed", False, f"{rec.name} timed out")
                    return
                except Exception as exc:
                    self._finish(rec, "failed", False, f"{rec.name} crashed: {exc}")
                    return
                Path(rec.log_path).write_text(out + ("\n--- stderr ---\n" + err if err else ""))
                ok, summary = summarize(out)
                ok = ok and code == 0
                self._finish(rec, "done" if ok else "failed", ok, summary or f"exit code {code}")
        except asyncio.CancelledError:
            self._finish(rec, "cancelled", False, f"{rec.name} cancelled")
            raise
        except Exception as exc:
            self._finish(rec, "failed", False, f"{rec.name} crashed: {exc}")

    def _finish(self, rec: JobRecord, status: str, ok: bool, summary: str) -> None:
        rec.status = status
        rec.ok = ok
        rec.summary = summary
        rec.finished = _now()
        self.store.save(rec)
        self.events.put_nowait(JobFinished(rec))


def claude_runner(cwd: Path, allowed_tools: list[str], model: str | None = None) -> Runner:
    """Real worker: `claude -p` in cwd, JSON output, no interactive prompts.

    `allowed_tools` is the *worker* allowlist (BrainConfig.worker_allowed_tools), not the
    concierge's read-only one: a headless worker has nobody to answer a permission prompt,
    so anything outside the list is denied. Worker safety therefore relies on the synced
    PreToolUse security-gate hook (~/.claude/settings.json), which can only block, never
    approve. `mcp__server__*` wildcards are accepted by Claude Code in --allowedTools.
    """

    async def run(rec: JobRecord) -> tuple[int, str, str]:
        cmd = [
            "claude",
            "-p",
            rec.prompt,
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            ",".join(allowed_tools),
        ]
        if model:
            cmd += ["--model", model]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        rec.pid = proc.pid
        try:
            out, err = await proc.communicate()
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    return run
