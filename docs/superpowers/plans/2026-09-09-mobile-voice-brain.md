# Mobile Voice Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `synthia-brain` service on middo247 that holds one warm Claude Agent SDK session in `~/dev/eventflo`, runs long jobs as headless Claude Code workers, and talks to Mark over Telegram voice notes.

**Architecture:** `Brain` wraps a long-lived `ClaudeSDKClient` and exposes three calls (`send`, `events`, `interrupt`). A `JobManager` runs `claude -p` subprocesses and pushes `JobFinished` events that the brain speaks when idle. A permission callback built on Synthia's existing security-gate rules turns risky tool calls into voice confirmations. Transports (Telegram now) only touch the three brain calls plus a `Speech` helper.

**Tech Stack:** Python 3.12, `claude-agent-sdk` (0.2.x), `python-telegram-bot` 22, `google-cloud-speech`, `google-cloud-texttospeech`, asyncio, pytest + pytest-asyncio, systemd, Syncthing.

**Spec:** `docs/superpowers/specs/2026-09-09-mobile-voice-brain-design.md`

## Global Constraints

- Python quality gates must pass before every commit: `black --check src/ tests/`, `isort --check src/ tests/`, `mypy src/synthia/ --ignore-missing-imports`, `pytest tests/ --tb=short -q`.
- Never use `permission_mode="bypassPermissions"` anywhere (spec Section 6).
- Working directory for the concierge and workers is `~/dev/eventflo` (spec Section 1).
- `setting_sources=["user", "project", "local"]` on the concierge (spec Section 1).
- Max two concurrent workers, 30-minute worker timeout, summaries truncated to ~600 chars (spec Section 2).
- Telegram whitelist: unknown users are ignored silently (spec Section 4).
- Voice confirmation timeout: two minutes, default deny (spec Section 6).
- Never log audio (spec Section 6).
- Write "Synthia" with a capital S in all docs and strings.
- Conventional commits, one commit per task, on the `development` branch (or a feature branch off it).
- All new modules live in `src/synthia/brain/`; tests in `tests/brain/`.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `scripts/brain_auth_spike.py` | Throwaway: proves Agent SDK auth on middo247 (Task 1). |
| `src/synthia/brain/__init__.py` | Package marker, exports `Brain`. |
| `src/synthia/brain/config.py` | `BrainConfig` dataclass + `load_brain_config()` from `~/.config/synthia/brain.yaml` and env. |
| `src/synthia/brain/jobs.py` | `JobRecord`, `JobStore` (JSON files), `JobManager` (dispatch, concurrency, timeout, events). |
| `src/synthia/brain/job_tools.py` | Four in-process MCP tools wrapping `JobManager`; `build_jobs_server()`. |
| `src/synthia/brain/gate.py` | `classify()` on top of `security_gate.evaluate()`; `make_can_use_tool()`. |
| `src/synthia/brain/persona.py` | Voice persona text and `build_system_prompt()`. |
| `src/synthia/brain/concierge.py` | `Brain`: session lifecycle, `send`, `events`, `interrupt`, rollover, idle gating. |
| `src/synthia/brain/speech.py` | `Speech.transcribe_ogg()` and `Speech.speak_to_ogg()` via Google Cloud, phrase hints, chunking. |
| `src/synthia/brain/transports/__init__.py` | Package marker. |
| `src/synthia/brain/transports/telegram.py` | `TelegramTransport`: voice in/out, event pump, commands, confirmation flow. |
| `src/synthia/brain/cli.py` | `synthia-brain repl` and `synthia-brain telegram`; repo pull at startup. |
| `deploy/brain/*` | systemd units, timer, env/yaml examples, install notes. |
| `docs/brain.md` | Operator doc: install, sync, run, troubleshoot. |
| `tests/brain/*` | One test module per source module. |

---

### Task 1: Auth spike on middo247 (throwaway)

**Files:**
- Create: `scripts/brain_auth_spike.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a written answer in `docs/brain.md` (Task 11) to "does the Agent SDK on middo247 run on the Claude Max login, or does it need `ANTHROPIC_API_KEY`?" and the resulting `model` default.

- [ ] **Step 1: Write the spike script**

```python
#!/usr/bin/env python3
"""Throwaway: does claude-agent-sdk authenticate on this box, and with what?

Run on middo247 after `pip install claude-agent-sdk` and `claude login`:
    python scripts/brain_auth_spike.py
"""

import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage


async def main() -> None:
    print("ANTHROPIC_API_KEY set:", bool(os.environ.get("ANTHROPIC_API_KEY")))
    options = ClaudeAgentOptions(
        cwd=os.path.expanduser("~/dev/eventflo"),
        setting_sources=["user", "project", "local"],
        max_turns=1,
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Reply with one line: which model are you and what is today's date?")
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                print("subtype:", message.subtype)
                print("is_error:", message.is_error)
                print("result:", message.result)
                print("total_cost_usd:", message.total_cost_usd)
                print("model_usage:", message.model_usage)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it on the server, twice**

```bash
ssh server "cd ~/dev/misc/synthia && source venv/bin/activate && pip install claude-agent-sdk && env -u ANTHROPIC_API_KEY python scripts/brain_auth_spike.py"
ssh server "cd ~/dev/misc/synthia && source venv/bin/activate && python scripts/brain_auth_spike.py"
```

If `~/dev/misc/synthia` does not exist on the server yet, `git clone` it first and create the venv with `python3 -m venv venv && source venv/bin/activate && pip install -e '.[dev]'`.

Expected: the first run (no API key) either succeeds with `total_cost_usd: None` or `0.0` (Max login works) or fails with an authentication error (API key required). Record the exact outcome.

- [ ] **Step 3: Record the finding**

Write the outcome as a note for Task 11's `docs/brain.md` (section "Authentication"). If an API key is required, stop and tell Mark before continuing: the `model` default in `BrainConfig` (Task 2) becomes his cost decision.

- [ ] **Step 4: Commit**

```bash
git add scripts/brain_auth_spike.py
git commit -m "chore(brain): auth spike script for Agent SDK on middo247"
```

---

### Task 2: Package skeleton, dependencies, config

**Files:**
- Create: `src/synthia/brain/__init__.py`, `src/synthia/brain/config.py`, `src/synthia/brain/transports/__init__.py`, `tests/brain/__init__.py`, `tests/brain/test_config.py`
- Modify: `pyproject.toml` (optional-dependencies, scripts, pytest ini)

**Interfaces:**
- Produces: `BrainConfig` dataclass and `load_brain_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> BrainConfig`.

- [ ] **Step 1: Add dependencies and entry point**

In `pyproject.toml`:

```toml
[project.optional-dependencies]
# ... existing groups unchanged ...
brain = [
    "claude-agent-sdk>=0.2.150",
    "python-telegram-bot>=20.0",
    "google-cloud-speech>=2.0",
    "google-cloud-texttospeech>=2.0",
    "pyyaml>=6.0",
]
all = ["synthia[local,cloud,remote,search,tui,brain]"]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.23",
    # ... rest unchanged ...
]

[project.scripts]
synthia = "synthia.main:main"
synthia-dash = "synthia.dashboard:main"
synthia-brain = "synthia.brain.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
```

Then: `source venv/bin/activate && pip install -e ".[dev,brain]"`.

- [ ] **Step 2: Write the failing config test**

`tests/brain/test_config.py`:

```python
from pathlib import Path

import yaml

from synthia.brain.config import BrainConfig, load_brain_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_brain_config(path=tmp_path / "missing.yaml", env={})
    assert cfg.cwd == Path.home() / "dev" / "eventflo"
    assert cfg.max_workers == 2
    assert cfg.job_timeout_s == 1800
    assert cfg.confirm_timeout_s == 120
    assert cfg.telegram_token == ""
    assert cfg.telegram_allowed_users == []
    assert "eventflo" in cfg.phrase_hints


def test_yaml_and_env_override(tmp_path):
    p = tmp_path / "brain.yaml"
    p.write_text(
        yaml.dump(
            {
                "cwd": "/srv/eventflo",
                "repos": ["/srv/eventflo/eva-ai"],
                "max_workers": 1,
                "voice": "en-AU-Neural2-D",
                "telegram_allowed_users": [42],
                "telegram_chat_id": 42,
                "phrase_hints": ["FloSale"],
            }
        )
    )
    cfg = load_brain_config(path=p, env={"BRAIN_TELEGRAM_TOKEN": "tok"})
    assert cfg.cwd == Path("/srv/eventflo")
    assert cfg.repos == [Path("/srv/eventflo/eva-ai")]
    assert cfg.max_workers == 1
    assert cfg.voice == "en-AU-Neural2-D"
    assert cfg.telegram_allowed_users == [42]
    assert cfg.telegram_chat_id == 42
    assert cfg.telegram_token == "tok"
    assert cfg.phrase_hints == ["FloSale"]


def test_unknown_key_ignored_with_warning(tmp_path, caplog):
    p = tmp_path / "brain.yaml"
    p.write_text(yaml.dump({"bogus": 1}))
    cfg = load_brain_config(path=p, env={})
    assert isinstance(cfg, BrainConfig)
    assert "bogus" in caplog.text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/brain/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain'`

- [ ] **Step 4: Write the package and config module**

`src/synthia/brain/__init__.py`:

```python
"""Synthia mobile voice brain: warm Claude Agent SDK concierge plus job workers."""
```

`src/synthia/brain/transports/__init__.py`:

```python
"""Transports that carry text and audio between Mark and the brain."""
```

`tests/brain/__init__.py`: empty file.

`src/synthia/brain/config.py`:

```python
"""Brain configuration: ~/.config/synthia/brain.yaml plus environment secrets."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".config" / "synthia" / "brain.yaml"
DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "synthia" / "brain"

DEFAULT_PHRASE_HINTS = ["eventflo", "Eva", "Eva Core", "Barry", "FloSale", "Vishal", "Corey"]

DEFAULT_ALLOWED_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "Skill",
    "WebFetch",
    "WebSearch",
    "mcp__jobs__dispatch_job",
    "mcp__jobs__job_status",
    "mcp__jobs__list_jobs",
    "mcp__jobs__cancel_job",
]


@dataclass
class BrainConfig:
    cwd: Path = field(default_factory=lambda: Path.home() / "dev" / "eventflo")
    repos: list[Path] = field(default_factory=list)
    state_dir: Path = field(default_factory=lambda: DEFAULT_STATE_DIR)
    model: str | None = None
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    max_workers: int = 2
    job_timeout_s: int = 1800
    language: str = "en-AU"
    voice: str = "en-AU-Neural2-B"
    phrase_hints: list[str] = field(default_factory=lambda: list(DEFAULT_PHRASE_HINTS))
    telegram_token: str = ""
    telegram_allowed_users: list[int] = field(default_factory=list)
    telegram_chat_id: int | None = None
    confirm_timeout_s: int = 120


_PATH_FIELDS = {"cwd", "state_dir"}
_PATH_LIST_FIELDS = {"repos"}


def load_brain_config(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> BrainConfig:
    """Load config from YAML, then overlay secrets from the environment."""
    path = path or DEFAULT_PATH
    env = os.environ if env is None else env
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

    known = {f.name for f in fields(BrainConfig)}
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in known:
            logger.warning("brain.yaml: unknown key %r ignored", key)
            continue
        if key in _PATH_FIELDS:
            kwargs[key] = Path(os.path.expanduser(str(value)))
        elif key in _PATH_LIST_FIELDS:
            kwargs[key] = [Path(os.path.expanduser(str(v))) for v in value]
        else:
            kwargs[key] = value

    cfg = BrainConfig(**kwargs)
    token = env.get("BRAIN_TELEGRAM_TOKEN")
    if token:
        cfg.telegram_token = token
    return cfg
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/brain/test_config.py -v`
Expected: 3 PASS

- [ ] **Step 6: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add pyproject.toml src/synthia/brain tests/brain
git commit -m "feat(brain): package skeleton, config loader, brain extra"
```

---

### Task 3: Job store and manager

**Files:**
- Create: `src/synthia/brain/jobs.py`, `tests/brain/test_jobs.py`

**Interfaces:**
- Produces:
  - `@dataclass JobRecord(id: str, name: str, prompt: str, started: str, finished: str | None = None, ok: bool | None = None, summary: str = "", log_path: str = "", pid: int | None = None, status: str = "queued", delivered: bool = False)` with `status` in `{"queued", "running", "done", "failed", "cancelled"}`.
  - `@dataclass JobFinished(job: JobRecord)`.
  - `JobStore(root: Path)` with `save(record)`, `load(job_id) -> JobRecord | None`, `list_all() -> list[JobRecord]`, `undelivered() -> list[JobRecord]`.
  - `Runner = Callable[[JobRecord], Awaitable[tuple[int, str, str]]]` returning `(returncode, stdout, stderr)`.
  - `JobManager(store, events: asyncio.Queue[JobFinished], runner: Runner, max_workers: int = 2, timeout_s: int = 1800)` with `async dispatch(name, prompt) -> JobRecord`, `status(job_id) -> JobRecord | None`, `list_jobs() -> list[JobRecord]`, `async cancel(job_id) -> bool`, `async shutdown()`.
  - `claude_runner(cwd: Path, allowed_tools: list[str], model: str | None) -> Runner` (real subprocess). Workers get the Synthia security gate as a PreToolUse hook automatically because `~/.claude/settings.json` (synced from the desktop, Task 10) registers `security_gate.py`; no extra wiring here.
  - `summarize(stdout: str, limit: int = 600) -> tuple[bool, str]` parses `claude -p --output-format json` output.

- [ ] **Step 1: Write the failing tests**

`tests/brain/test_jobs.py`:

```python
import asyncio
import json

import pytest

from synthia.brain.jobs import JobFinished, JobManager, JobStore, summarize


def _ok_stdout(text="all done"):
    return json.dumps({"type": "result", "is_error": False, "result": text, "session_id": "s"})


def test_summarize_parses_result_json():
    ok, summary = summarize(_ok_stdout("Briefing ready. Three meetings."))
    assert ok is True
    assert summary == "Briefing ready. Three meetings."


def test_summarize_truncates_and_handles_garbage():
    ok, summary = summarize(_ok_stdout("x" * 2000), limit=600)
    assert ok is True
    assert len(summary) == 600
    ok, summary = summarize("not json at all")
    assert ok is False
    assert "not json at all" in summary


def test_store_roundtrip(tmp_path):
    from synthia.brain.jobs import JobRecord

    store = JobStore(tmp_path)
    rec = JobRecord(id="abc", name="morning", prompt="/morning", started="2026-09-09T07:00:00")
    store.save(rec)
    loaded = store.load("abc")
    assert loaded == rec
    assert store.list_all() == [rec]
    rec.status = "done"
    rec.finished = "2026-09-09T07:05:00"
    store.save(rec)
    assert store.undelivered() == [rec]


async def test_dispatch_runs_and_emits_event(tmp_path):
    events: asyncio.Queue[JobFinished] = asyncio.Queue()

    async def runner(rec):
        return 0, _ok_stdout("summary here"), ""

    mgr = JobManager(JobStore(tmp_path), events, runner, max_workers=2, timeout_s=5)
    rec = await mgr.dispatch("morning", "/morning")
    assert rec.status in ("queued", "running")
    ev = await asyncio.wait_for(events.get(), 2)
    assert ev.job.id == rec.id
    assert ev.job.status == "done"
    assert ev.job.ok is True
    assert ev.job.summary == "summary here"
    assert mgr.status(rec.id).status == "done"
    await mgr.shutdown()


async def test_concurrency_limit_queues_third_job(tmp_path):
    events: asyncio.Queue[JobFinished] = asyncio.Queue()
    gate = asyncio.Event()
    running = 0
    peak = 0

    async def runner(rec):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await gate.wait()
        running -= 1
        return 0, _ok_stdout("ok"), ""

    mgr = JobManager(JobStore(tmp_path), events, runner, max_workers=2, timeout_s=5)
    for i in range(3):
        await mgr.dispatch(f"j{i}", "p")
    await asyncio.sleep(0.05)
    assert peak == 2
    statuses = sorted(j.status for j in mgr.list_jobs())
    assert statuses == ["queued", "running", "running"]
    gate.set()
    for _ in range(3):
        await asyncio.wait_for(events.get(), 2)
    assert peak == 2
    await mgr.shutdown()


async def test_timeout_marks_failed(tmp_path):
    events: asyncio.Queue[JobFinished] = asyncio.Queue()

    async def runner(rec):
        await asyncio.sleep(10)
        return 0, "", ""

    mgr = JobManager(JobStore(tmp_path), events, runner, max_workers=1, timeout_s=0.05)
    await mgr.dispatch("slow", "p")
    ev = await asyncio.wait_for(events.get(), 2)
    assert ev.job.status == "failed"
    assert ev.job.ok is False
    assert "timed out" in ev.job.summary
    await mgr.shutdown()


async def test_cancel_running_job(tmp_path):
    events: asyncio.Queue[JobFinished] = asyncio.Queue()

    async def runner(rec):
        await asyncio.sleep(10)
        return 0, "", ""

    mgr = JobManager(JobStore(tmp_path), events, runner, max_workers=1, timeout_s=5)
    rec = await mgr.dispatch("slow", "p")
    await asyncio.sleep(0.01)
    assert await mgr.cancel(rec.id) is True
    ev = await asyncio.wait_for(events.get(), 2)
    assert ev.job.status == "cancelled"
    assert await mgr.cancel("nope") is False
    await mgr.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain.jobs'`

- [ ] **Step 3: Implement jobs.py**

```python
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
                Path(rec.log_path).write_text(out + ("\n--- stderr ---\n" + err if err else ""))
                ok, summary = summarize(out)
                ok = ok and code == 0
                self._finish(rec, "done" if ok else "failed", ok, summary or f"exit code {code}")
        except asyncio.CancelledError:
            self._finish(rec, "cancelled", False, f"{rec.name} cancelled")
            raise

    def _finish(self, rec: JobRecord, status: str, ok: bool, summary: str) -> None:
        rec.status = status
        rec.ok = ok
        rec.summary = summary
        rec.finished = _now()
        self.store.save(rec)
        self.events.put_nowait(JobFinished(rec))


def claude_runner(cwd: Path, allowed_tools: list[str], model: str | None = None) -> Runner:
    """Real worker: `claude -p` in cwd, JSON output, no interactive prompts."""

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
            raise
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    return run
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_jobs.py -v`
Expected: 7 PASS

- [ ] **Step 5: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/jobs.py tests/brain/test_jobs.py
git commit -m "feat(brain): job store and manager for headless Claude workers"
```

---

### Task 4: Job MCP tools

**Files:**
- Create: `src/synthia/brain/job_tools.py`, `tests/brain/test_job_tools.py`

**Interfaces:**
- Consumes: `JobManager` (Task 3).
- Produces: `build_jobs_server(manager: JobManager) -> McpSdkServerConfig` registering tools `dispatch_job`, `job_status`, `list_jobs`, `cancel_job` under server name `jobs` (so tool names are `mcp__jobs__*`, matching `DEFAULT_ALLOWED_TOOLS`). Also `make_tools(manager) -> list[SdkMcpTool]` for tests.

- [ ] **Step 1: Write the failing tests**

`tests/brain/test_job_tools.py`:

```python
import asyncio
import json

from synthia.brain.job_tools import build_jobs_server, make_tools
from synthia.brain.jobs import JobFinished, JobManager, JobStore


def _ok(text):
    return json.dumps({"type": "result", "is_error": False, "result": text})


async def _mgr(tmp_path, block=None):
    async def runner(rec):
        if block:
            await block.wait()
        return 0, _ok("done: " + rec.name), ""

    return JobManager(JobStore(tmp_path), asyncio.Queue(), runner, max_workers=2, timeout_s=5)


def _by_name(tools):
    return {t.name: t for t in tools}


async def test_dispatch_and_status(tmp_path):
    mgr = await _mgr(tmp_path)
    tools = _by_name(make_tools(mgr))
    out = await tools["dispatch_job"].handler({"name": "morning", "prompt": "/morning"})
    text = out["content"][0]["text"]
    assert "morning" in text and "dispatched" in text
    job_id = text.split("id ")[1].split()[0]
    await asyncio.sleep(0.05)
    out = await tools["job_status"].handler({"job_id": job_id})
    assert "done" in out["content"][0]["text"]
    await mgr.shutdown()


async def test_list_and_cancel(tmp_path):
    block = asyncio.Event()
    mgr = await _mgr(tmp_path, block)
    tools = _by_name(make_tools(mgr))
    await tools["dispatch_job"].handler({"name": "slow", "prompt": "p"})
    out = await tools["list_jobs"].handler({})
    assert "slow" in out["content"][0]["text"]
    rec = mgr.list_jobs()[0]
    out = await tools["cancel_job"].handler({"job_id": rec.id})
    assert "cancelled" in out["content"][0]["text"]
    out = await tools["cancel_job"].handler({"job_id": "nope"})
    assert out.get("is_error") is True
    block.set()
    await mgr.shutdown()


async def test_server_config_shape(tmp_path):
    mgr = await _mgr(tmp_path)
    cfg = build_jobs_server(mgr)
    assert cfg["type"] == "sdk"
    assert cfg["name"] == "jobs"
    await mgr.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_job_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain.job_tools'`

- [ ] **Step 3: Implement job_tools.py**

```python
"""In-process MCP tools the concierge uses to run and track background jobs."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from synthia.brain.jobs import JobManager, JobRecord


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


def _line(rec: JobRecord) -> str:
    tail = f": {rec.summary}" if rec.summary else ""
    return f"{rec.name} (id {rec.id}) {rec.status}{tail}"


def make_tools(manager: JobManager) -> list[SdkMcpTool[Any]]:
    @tool(
        "dispatch_job",
        "Run a long task in the background as a headless Claude Code worker in the eventflo "
        "folder. Use for anything over about thirty seconds (morning briefing, builds, audits). "
        "The prompt can be a skill like '/morning' or plain instructions. Returns immediately; "
        "you will be told when it finishes.",
        {"name": str, "prompt": str},
    )
    async def dispatch_job(args: dict[str, Any]) -> dict[str, Any]:
        rec = await manager.dispatch(args["name"], args["prompt"])
        return _text(f"{rec.name} dispatched, id {rec.id}. I'll report when it finishes.")

    @tool("job_status", "Status and summary of one background job.", {"job_id": str})
    async def job_status(args: dict[str, Any]) -> dict[str, Any]:
        rec = manager.status(args["job_id"])
        if rec is None:
            return _text(f"No job with id {args['job_id']}.", is_error=True)
        return _text(_line(rec))

    @tool("list_jobs", "List background jobs from this session with their status.", {})
    async def list_jobs(args: dict[str, Any]) -> dict[str, Any]:
        jobs = manager.list_jobs()
        if not jobs:
            return _text("No jobs yet.")
        return _text("\n".join(_line(r) for r in jobs))

    @tool("cancel_job", "Cancel a queued or running background job.", {"job_id": str})
    async def cancel_job(args: dict[str, Any]) -> dict[str, Any]:
        if await manager.cancel(args["job_id"]):
            return _text(f"Job {args['job_id']} cancelled.")
        return _text(f"Job {args['job_id']} is not running.", is_error=True)

    return [dispatch_job, job_status, list_jobs, cancel_job]


def build_jobs_server(manager: JobManager) -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="jobs", version="1.0.0", tools=make_tools(manager))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_job_tools.py -v`
Expected: 3 PASS

- [ ] **Step 5: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/job_tools.py tests/brain/test_job_tools.py
git commit -m "feat(brain): job dispatch MCP tools for the concierge"
```

---

### Task 5: Permission gate with voice confirmation

**Files:**
- Create: `src/synthia/brain/gate.py`, `tests/brain/test_gate.py`

**Interfaces:**
- Consumes: `synthia.hooks.security_gate.evaluate(tool, tool_input) -> list[dict]` and `SEV_RANK`, `CRITICAL`, `HIGH` from the same module.
- Produces:
  - `Decision = Literal["allow", "deny", "confirm"]`
  - `classify(tool_name: str, tool_input: dict) -> tuple[Decision, str]` (decision, human reason).
  - `Confirmer = Callable[[str], Awaitable[bool]]`
  - `make_can_use_tool(confirm: Confirmer) -> CanUseTool` returning `PermissionResultAllow` / `PermissionResultDeny`.
  - `describe(tool_name, tool_input) -> str` one spoken line ("run git push origin main").

- [ ] **Step 1: Write the failing tests**

`tests/brain/test_gate.py`:

```python
import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext

from synthia.brain.gate import classify, describe, make_can_use_tool


@pytest.mark.parametrize(
    "tool,inp,expected",
    [
        ("Bash", {"command": "ls -la"}, "allow"),
        ("Bash", {"command": "rm -rf /"}, "deny"),
        ("Bash", {"command": "git push origin main"}, "confirm"),
        ("Bash", {"command": "git push --force origin feat/x"}, "confirm"),
        ("Bash", {"command": "ssh server 'sudo systemctl restart eva-core'"}, "confirm"),
        ("Bash", {"command": "mongosh prod --eval 'db.users.deleteMany({})'"}, "confirm"),
        ("Bash", {"command": "gh pr merge 123"}, "confirm"),
        ("Write", {"file_path": "/home/markmiddo/dev/eventflo/README.md"}, "allow"),
        ("Write", {"file_path": "/home/markmiddo/.ssh/authorized_keys"}, "deny"),
        ("Read", {"file_path": "/home/markmiddo/dev/eventflo/x.py"}, "allow"),
    ],
)
def test_classify(tool, inp, expected):
    decision, _reason = classify(tool, inp)
    assert decision == expected


def test_describe_bash_and_write():
    assert describe("Bash", {"command": "git push origin main"}) == "run git push origin main"
    assert describe("Write", {"file_path": "/a/b.py"}) == "write /a/b.py"
    assert describe("Edit", {"file_path": "/a/b.py"}) == "edit /a/b.py"
    assert describe("Weird", {"x": 1}) == "use Weird"


async def test_can_use_tool_paths():
    asked: list[str] = []

    async def say_yes(q):
        asked.append(q)
        return True

    async def say_no(q):
        asked.append(q)
        return False

    ctx = ToolPermissionContext()
    allow = make_can_use_tool(say_yes)
    assert isinstance(await allow("Bash", {"command": "ls"}, ctx), PermissionResultAllow)
    assert asked == []
    assert isinstance(await allow("Bash", {"command": "rm -rf /"}, ctx), PermissionResultDeny)
    assert asked == []
    res = await allow("Bash", {"command": "git push origin main"}, ctx)
    assert isinstance(res, PermissionResultAllow)
    assert asked == ["run git push origin main"]

    deny = make_can_use_tool(say_no)
    res = await deny("Bash", {"command": "git push origin main"}, ctx)
    assert isinstance(res, PermissionResultDeny)
    assert "not confirmed" in res.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain.gate'`

- [ ] **Step 3: Implement gate.py**

```python
"""Permission gate: Synthia security-gate rules plus voice confirmation for risky calls."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Literal

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext

from synthia.hooks.security_gate import CRITICAL, HIGH, SEV_RANK, evaluate

Decision = Literal["allow", "deny", "confirm"]
Confirmer = Callable[[str], Awaitable[bool]]

# Actions that are legitimate but must be confirmed by voice first.
RISKY_BASH = [
    ("git-push", re.compile(r"\bgit\s+push\b")),
    ("pr-merge", re.compile(r"\bgh\s+pr\s+merge\b")),
    ("service-restart", re.compile(r"\bsystemctl\s+(restart|stop|disable)\b")),
    ("deploy", re.compile(r"\b(deploy|release)\b", re.IGNORECASE)),
    ("db-write", re.compile(r"\b(deleteMany|deleteOne|updateMany|drop\(|dropDatabase)\b")),
    ("git-destructive", re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-f|branch\s+-D)\b")),
    ("recursive-delete", re.compile(r"\brm\s+-[a-zA-Z]*r")),
]


def describe(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        return f"run {tool_input.get('command', '')}".strip()
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        verb = "write" if tool_name == "Write" else "edit"
        return f"{verb} {tool_input.get('file_path', '')}".strip()
    return f"use {tool_name}"


def classify(tool_name: str, tool_input: dict[str, Any]) -> tuple[Decision, str]:
    hits = evaluate(tool_name, tool_input)
    if hits:
        top = max(hits, key=lambda h: SEV_RANK.get(h["severity"], 0))
        if top["severity"] == CRITICAL:
            return "deny", f"blocked by rule {top['rule']}"
        if top["severity"] == HIGH:
            return "confirm", f"flagged by rule {top['rule']}"
    if tool_name == "Bash":
        cmd = tool_input.get("command", "") or ""
        for name, pat in RISKY_BASH:
            if pat.search(cmd):
                return "confirm", f"risky action {name}"
    return "allow", "ok"


def make_can_use_tool(confirm: Confirmer) -> Callable[..., Awaitable[Any]]:
    async def can_use_tool(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        decision, reason = classify(tool_name, tool_input)
        if decision == "allow":
            return PermissionResultAllow(updated_input=tool_input)
        if decision == "deny":
            return PermissionResultDeny(message=f"Denied: {reason}.")
        if await confirm(describe(tool_name, tool_input)):
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=f"Denied: {reason}, not confirmed by Mark.")

    return can_use_tool
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_gate.py -v`
Expected: all PASS. If a parametrized case disagrees with `security_gate.evaluate` (for example `rm -rf /` not rated critical), read `BASH_RULES` in `src/synthia/hooks/security_gate.py` and adjust the test input to a command that rule actually matches rather than weakening the gate.

- [ ] **Step 5: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/gate.py tests/brain/test_gate.py
git commit -m "feat(brain): permission gate with voice confirmation for risky calls"
```

---

### Task 6: Concierge brain

**Files:**
- Create: `src/synthia/brain/persona.py`, `src/synthia/brain/concierge.py`, `tests/brain/test_concierge.py`
- Modify: `src/synthia/brain/__init__.py` (export `Brain`)

**Interfaces:**
- Consumes: `BrainConfig` (Task 2), `JobManager`, `JobFinished`, `JobStore`, `claude_runner` (Task 3), `build_jobs_server` (Task 4), `make_can_use_tool`, `Confirmer` (Task 5).
- Produces:
  - `build_system_prompt(handover: str | None = None) -> SystemPromptPreset` (from `claude_agent_sdk.types`).
  - `ClientLike` protocol: `connect()`, `query(prompt)`, `receive_response()`, `interrupt()`, `disconnect()`.
  - `ClientFactory = Callable[[ClaudeAgentOptions], ClientLike]`.
  - `@dataclass SpokenEvent(job: JobRecord, text: str)`.
  - `Brain(config, confirm: Confirmer, client_factory=None, runner=None, today=date.today)` with:
    - `async start() -> None`, `async stop() -> None`
    - `send(text: str) -> AsyncIterator[str]` (text deltas)
    - `events() -> AsyncIterator[SpokenEvent]`
    - `async interrupt() -> None`
    - `async new_session() -> None`
    - `jobs: JobManager`
    - `session_id: str | None`

- [ ] **Step 1: Write persona.py**

```python
"""Voice persona appended to the Claude Code system prompt."""

from __future__ import annotations

from claude_agent_sdk.types import SystemPromptPreset

PERSONA = """
# Voice mode

You are talking to Mark by voice while he walks. Everything you write is read aloud
by text to speech, so:

- Reply in two to four short sentences. No markdown, no lists, no code, no file paths,
  no URLs. Say numbers as words where natural.
- Be direct and warm. You are the same assistant Mark works with at his desk, with the
  same skills, memory and connectors, just speaking instead of typing.
- Anything that will take longer than about thirty seconds (the morning briefing, a
  build, an audit, a long email triage) must go through the dispatch_job tool. Say one
  short line like "on it, briefing in a few minutes" and dispatch. Do not do long work
  inline.
- Quick things (calendar changes, adding tasks, lookups, short answers) you do inline.
- When a message starting with [job event] arrives, summarise that job's result in one
  breath, then stop. Do not repeat the raw summary verbatim if it is long.
- If a tool call needs Mark's confirmation you will be told; ask him plainly and wait.
- If you did not understand a transcript, say so and ask him to repeat.
""".strip()


def build_system_prompt(handover: str | None = None) -> SystemPromptPreset:
    text = PERSONA
    if handover:
        text += "\n\n# Handover from yesterday's session\n\n" + handover.strip()
    return {"type": "preset", "preset": "claude_code", "append": text}
```

- [ ] **Step 2: Write the failing concierge tests**

`tests/brain/test_concierge.py`:

```python
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage, StreamEvent

from synthia.brain.concierge import Brain, SpokenEvent
from synthia.brain.config import BrainConfig


class FakeClient:
    """Scripted stand-in for ClaudeSDKClient."""

    instances: list["FakeClient"] = []

    def __init__(self, options):
        self.options = options
        self.queries: list[str] = []
        self.interrupted = False
        self.connected = False
        self.reply = "hello there"
        FakeClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def query(self, prompt, session_id="default"):
        self.queries.append(prompt)

    async def interrupt(self):
        self.interrupted = True

    async def receive_response(self):
        for word in self.reply.split(" "):
            yield StreamEvent(
                uuid="u",
                session_id="sess-1",
                event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": word + " "}},
            )
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sess-1",
            result=self.reply,
        )


@pytest.fixture(autouse=True)
def _reset():
    FakeClient.instances.clear()


def _cfg(tmp_path) -> BrainConfig:
    return BrainConfig(cwd=tmp_path, state_dir=tmp_path / "state", repos=[])


async def _yes(q):
    return True


async def _collect(agen):
    return "".join([chunk async for chunk in agen])


async def test_send_streams_and_persists_session(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None)
    await brain.start()
    text = await _collect(brain.send("hi"))
    assert text.strip() == "hello there"
    assert brain.session_id == "sess-1"
    saved = json.loads((tmp_path / "state" / "session.json").read_text())
    assert saved["session_id"] == "sess-1"
    assert saved["date"] == date.today().isoformat()
    opts = FakeClient.instances[0].options
    assert str(opts.cwd) == str(tmp_path)
    assert opts.setting_sources == ["user", "project", "local"]
    assert opts.permission_mode != "bypassPermissions"
    assert "jobs" in opts.mcp_servers
    assert opts.include_partial_messages is True
    await brain.stop()


async def test_resume_uses_saved_session_same_day(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "session.json").write_text(
        json.dumps({"session_id": "old-1", "date": date.today().isoformat()})
    )
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None)
    await brain.start()
    assert FakeClient.instances[0].options.resume == "old-1"
    await brain.stop()


async def test_rollover_on_new_day_carries_handover(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "session.json").write_text(json.dumps({"session_id": "old-1", "date": "2026-09-08"}))
    brain = Brain(
        _cfg(tmp_path),
        _yes,
        client_factory=FakeClient,
        runner=None,
        today=lambda: date(2026, 9, 9),
    )
    await brain.start()
    old = FakeClient.instances[0]
    assert old.options.resume == "old-1"
    old.reply = "Handover: shipped PR 12, follow up with Vishal."
    await _collect(brain.send("morning"))
    assert any("handover" in q.lower() for q in old.queries)
    new = FakeClient.instances[-1]
    assert new is not old
    assert new.options.resume is None
    assert "Handover: shipped PR 12" in new.options.system_prompt["append"]
    assert new.queries == ["morning"]
    await brain.stop()


async def test_job_event_spoken_when_idle(tmp_path):
    async def runner(rec):
        return 0, json.dumps({"is_error": False, "result": "Briefing done. Two meetings."}), ""

    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=runner)
    await brain.start()
    events = brain.events()
    await brain.jobs.dispatch("morning", "/morning")
    ev = await asyncio.wait_for(events.__anext__(), 2)
    assert isinstance(ev, SpokenEvent)
    assert ev.job.name == "morning"
    client = FakeClient.instances[-1]
    assert client.queries[-1].startswith("[job event] morning finished")
    assert "Briefing done" in client.queries[-1]
    assert ev.text.strip() == "hello there"
    assert brain.jobs.status(ev.job.id).delivered is True
    await brain.stop()


async def test_interrupt_drains_then_allows_send(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None)
    await brain.start()
    await brain.interrupt()
    assert FakeClient.instances[0].interrupted is True
    text = await _collect(brain.send("again"))
    assert text.strip() == "hello there"
    await brain.stop()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/brain/test_concierge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain.concierge'`

- [ ] **Step 4: Implement concierge.py**

```python
"""The concierge: one warm Claude Agent SDK session that talks and dispatches jobs."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Protocol

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent

from synthia.brain.config import BrainConfig
from synthia.brain.gate import Confirmer, make_can_use_tool
from synthia.brain.job_tools import build_jobs_server
from synthia.brain.jobs import JobFinished, JobManager, JobRecord, JobStore, Runner, claude_runner
from synthia.brain.persona import build_system_prompt

logger = logging.getLogger(__name__)

HANDOVER_PROMPT = (
    "This session is closing for the day. Write a five-line handover for tomorrow's "
    "session: what we worked on, anything unfinished, anything to remember. Plain text."
)


class ClientLike(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def query(self, prompt: str, session_id: str = "default") -> None: ...
    async def interrupt(self) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...


ClientFactory = Callable[[ClaudeAgentOptions], ClientLike]


@dataclass
class SpokenEvent:
    job: JobRecord
    text: str


def _delta_text(message: Any) -> str | None:
    if not isinstance(message, StreamEvent) or message.parent_tool_use_id:
        return None
    ev = message.event
    if ev.get("type") != "content_block_delta":
        return None
    delta = ev.get("delta") or {}
    if delta.get("type") != "text_delta":
        return None
    return str(delta.get("text", ""))


class Brain:
    def __init__(
        self,
        config: BrainConfig,
        confirm: Confirmer,
        client_factory: ClientFactory | None = None,
        runner: Runner | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.config = config
        self.confirm = confirm
        self._factory: ClientFactory = client_factory or (lambda o: ClaudeSDKClient(options=o))
        self._today = today
        self.session_id: str | None = None
        self._session_date: str | None = None
        self._client: ClientLike | None = None
        self._lock = asyncio.Lock()
        self._job_events: asyncio.Queue[JobFinished] = asyncio.Queue()
        config.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs = JobManager(
            JobStore(config.state_dir / "jobs"),
            self._job_events,
            runner or claude_runner(config.cwd, config.allowed_tools, config.model),
            max_workers=config.max_workers,
            timeout_s=config.job_timeout_s,
        )

    # ---- session persistence ----

    @property
    def _session_file(self) -> Path:
        return self.config.state_dir / "session.json"

    def _load_session(self) -> None:
        if self._session_file.exists():
            data = json.loads(self._session_file.read_text())
            self.session_id = data.get("session_id")
            self._session_date = data.get("date")

    def _save_session(self) -> None:
        self._session_file.write_text(
            json.dumps({"session_id": self.session_id, "date": self._session_date})
        )

    def _options(self, resume: str | None, handover: str | None) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(self.config.cwd),
            setting_sources=["user", "project", "local"],
            system_prompt=build_system_prompt(handover),
            skills="all",
            include_partial_messages=True,
            mcp_servers={"jobs": build_jobs_server(self.jobs)},
            allowed_tools=list(self.config.allowed_tools),
            permission_mode="default",
            can_use_tool=make_can_use_tool(self.confirm),
            model=self.config.model,
            resume=resume,
        )

    async def _open(self, resume: str | None, handover: str | None = None) -> None:
        self._client = self._factory(self._options(resume, handover))
        await self._client.connect()

    # ---- lifecycle ----

    async def start(self) -> None:
        self._load_session()
        await self._open(self.session_id)
        for rec in self.jobs.store.undelivered():
            self._job_events.put_nowait(JobFinished(rec))

    async def stop(self) -> None:
        await self.jobs.shutdown()
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def new_session(self, handover: str | None = None) -> None:
        if self._client is not None:
            await self._client.disconnect()
        self.session_id = None
        self._session_date = self._today().isoformat()
        self._save_session()
        await self._open(None, handover)

    async def _rollover_if_new_day(self) -> None:
        today = self._today().isoformat()
        if self._session_date == today or self.session_id is None:
            self._session_date = self._session_date or today
            return
        handover = await self._ask(HANDOVER_PROMPT)
        logger.info("Session rollover to %s", today)
        await self.new_session(handover)

    # ---- talking ----

    async def _ask(self, prompt: str) -> str:
        assert self._client is not None
        await self._client.query(prompt)
        parts: list[str] = []
        fallback = ""
        async for message in self._client.receive_response():
            text = _delta_text(message)
            if text:
                parts.append(text)
            elif isinstance(message, ResultMessage):
                self._note_result(message)
                fallback = message.result or ""
        return "".join(parts) if parts else fallback

    def _note_result(self, message: ResultMessage) -> None:
        if message.session_id and message.session_id != self.session_id:
            self.session_id = message.session_id
        self._session_date = self._session_date or self._today().isoformat()
        self._save_session()

    async def send(self, text: str) -> AsyncIterator[str]:
        async with self._lock:
            await self._rollover_if_new_day()
            assert self._client is not None
            await self._client.query(text)
            streamed = False
            async for message in self._client.receive_response():
                delta = _delta_text(message)
                if delta:
                    streamed = True
                    yield delta
                elif isinstance(message, ResultMessage):
                    self._note_result(message)
                    if not streamed and message.result:
                        yield message.result

    async def interrupt(self) -> None:
        if self._client is None:
            return
        await self._client.interrupt()
        async for _ in self._client.receive_response():
            pass

    async def events(self) -> AsyncIterator[SpokenEvent]:
        while True:
            finished = await self._job_events.get()
            rec = finished.job
            prompt = f"[job event] {rec.name} finished ({rec.status}): {rec.summary}"
            async with self._lock:
                await self._rollover_if_new_day()
                text = await self._ask(prompt)
            rec.delivered = True
            self.jobs.store.save(rec)
            yield SpokenEvent(rec, text)
```

Update `src/synthia/brain/__init__.py`:

```python
"""Synthia mobile voice brain: warm Claude Agent SDK concierge plus job workers."""

from synthia.brain.concierge import Brain, SpokenEvent

__all__ = ["Brain", "SpokenEvent"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/brain/test_concierge.py -v`
Expected: 5 PASS. Note for the rollover test: `FakeClient.receive_response` yields `session_id="sess-1"`, so after the handover turn the old client still reports `sess-1`; the new client is created with `resume=None` because `new_session()` clears `session_id` before opening.

- [ ] **Step 6: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/persona.py src/synthia/brain/concierge.py src/synthia/brain/__init__.py tests/brain/test_concierge.py
git commit -m "feat(brain): concierge session with streaming, rollover and job events"
```

---

### Task 7: CLI with text REPL and repo pull

**Files:**
- Create: `src/synthia/brain/cli.py`, `tests/brain/test_cli.py`

**Interfaces:**
- Consumes: `Brain`, `load_brain_config`.
- Produces:
  - `pull_repos(repos: list[Path], run=subprocess.run) -> list[tuple[Path, bool]]` (never raises).
  - `async repl(brain: Brain, input_fn=input, print_fn=print) -> None` (lines in, reply out, `/stop`, `/new`, `/jobs`, `/quit`).
  - `main(argv: list[str] | None = None) -> int` with subcommands `repl` and `telegram` (telegram wired in Task 9; until then it prints "telegram transport not built yet" and returns 2).

- [ ] **Step 1: Write the failing tests**

`tests/brain/test_cli.py`:

```python
import subprocess
from pathlib import Path

from synthia.brain.cli import main, pull_repos, repl


def test_pull_repos_reports_per_repo(tmp_path):
    calls = []

    def fake_run(cmd, cwd, capture_output, text, timeout):
        calls.append((cmd, cwd))
        if "bad" in str(cwd):
            return subprocess.CompletedProcess(cmd, 1, "", "fatal")
        return subprocess.CompletedProcess(cmd, 0, "Already up to date.", "")

    good, bad = tmp_path / "good", tmp_path / "bad"
    results = pull_repos([good, bad], run=fake_run)
    assert results == [(good, True), (bad, False)]
    assert calls[0][0] == ["git", "pull", "--ff-only"]


def test_pull_repos_swallows_exceptions(tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    assert pull_repos([tmp_path], run=boom) == [(tmp_path, False)]


class FakeBrain:
    def __init__(self):
        self.sent = []
        self.interrupts = 0
        self.new_sessions = 0

        class Jobs:
            def list_jobs(self_inner):
                return []

        self.jobs = Jobs()

    async def send(self, text):
        self.sent.append(text)
        yield "echo: "
        yield text

    async def interrupt(self):
        self.interrupts += 1

    async def new_session(self, handover=None):
        self.new_sessions += 1


async def test_repl_routes_lines_and_commands():
    brain = FakeBrain()
    lines = iter(["hello", "/stop", "/new", "/jobs", "/quit"])
    out = []
    await repl(brain, input_fn=lambda _p="": next(lines), print_fn=out.append)
    assert brain.sent == ["hello"]
    assert brain.interrupts == 1
    assert brain.new_sessions == 1
    assert any("echo: hello" in o for o in out)
    assert any("No jobs" in o for o in out)


def test_main_unknown_subcommand_returns_2(capsys):
    assert main(["bogus"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain.cli'`

- [ ] **Step 3: Implement cli.py**

```python
"""synthia-brain entry point: text REPL for desktop testing, Telegram transport for the walk."""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from synthia.brain.concierge import Brain
from synthia.brain.config import BrainConfig, load_brain_config

logger = logging.getLogger(__name__)


def pull_repos(
    repos: list[Path], run: Callable[..., Any] = subprocess.run
) -> list[tuple[Path, bool]]:
    results: list[tuple[Path, bool]] = []
    for repo in repos:
        try:
            proc = run(
                ["git", "pull", "--ff-only"], cwd=repo, capture_output=True, text=True, timeout=120
            )
            ok = proc.returncode == 0
            if not ok:
                logger.warning("git pull failed in %s: %s", repo, proc.stderr.strip())
        except Exception as e:  # never block the brain on a pull
            logger.warning("git pull errored in %s: %s", repo, e)
            ok = False
        results.append((repo, ok))
    return results


async def _always_yes(question: str) -> bool:
    print(f"[confirm] {question}")
    return input("yes/no> ").strip().lower() in ("y", "yes")


async def repl(
    brain: Any,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> None:
    print_fn("Synthia brain REPL. /stop interrupts, /new starts a session, /jobs lists, /quit exits.")
    while True:
        try:
            line = input_fn("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not line:
            continue
        if line == "/quit":
            return
        if line == "/stop":
            await brain.interrupt()
            print_fn("[interrupted]")
            continue
        if line == "/new":
            await brain.new_session()
            print_fn("[new session]")
            continue
        if line == "/jobs":
            jobs = brain.jobs.list_jobs()
            print_fn("No jobs." if not jobs else "\n".join(f"{j.name} {j.status}" for j in jobs))
            continue
        chunks = [c async for c in brain.send(line)]
        print_fn("brain> " + "".join(chunks))


async def _run_repl(cfg: BrainConfig) -> None:
    pull_repos(cfg.repos)
    brain = Brain(cfg, _always_yes)
    await brain.start()
    try:
        await repl(brain)
    finally:
        await brain.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthia-brain")
    parser.add_argument("command", choices=["repl", "telegram"])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = load_brain_config(path=args.config)
    if args.command == "repl":
        asyncio.run(_run_repl(cfg))
        return 0
    if args.command == "telegram":
        from synthia.brain.transports.telegram import run_telegram

        return run_telegram(cfg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

Until Task 9 lands, create a placeholder `src/synthia/brain/transports/telegram.py`:

```python
"""Telegram transport (built in Task 9)."""

from synthia.brain.config import BrainConfig


def run_telegram(cfg: BrainConfig) -> int:
    print("telegram transport not built yet")
    return 2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_cli.py -v`
Expected: 4 PASS

- [ ] **Step 5: Manual smoke from the desktop**

```bash
source venv/bin/activate && pip install -e ".[dev,brain]"
synthia-brain repl -v
```

Type `what's on my calendar today` and expect a spoken-style short reply. Type `/quit`. If the SDK cannot find the CLI, set `cli_path` is not needed: `claude` is on PATH at `~/.local/bin/claude`.

- [ ] **Step 6: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/cli.py src/synthia/brain/transports/telegram.py tests/brain/test_cli.py
git commit -m "feat(brain): synthia-brain CLI with text REPL and repo pull"
```

---

### Task 8: Speech (Google STT/TTS, ogg in and out)

**Files:**
- Create: `src/synthia/brain/speech.py`, `tests/brain/test_speech.py`

**Interfaces:**
- Consumes: `BrainConfig.language`, `.voice`, `.phrase_hints`.
- Produces: `Speech(language, voice, phrase_hints, stt_client=None, tts_client=None)` with `transcribe_ogg(path: Path) -> str`, `speak_to_ogg(text: str, out_dir: Path) -> list[Path]`, and module function `split_for_tts(text: str, limit: int = 3000) -> list[str]`.

Deliberate deviation from spec Section 3: when Google TTS fails the transport (Task 9) sends the reply as a text message instead of falling back to Piper. Piper is not installed on middo247 and a text fallback is simpler and still readable on the phone. Revisit only if Google TTS proves flaky.

Design note: Google STT accepts `OGG_OPUS` at 48 kHz directly (Telegram voice notes are 48 kHz Opus) and Google TTS emits `OGG_OPUS` directly, so no ffmpeg step is needed. Clients are injectable for tests; real clients are created lazily so importing the module never touches Google.

- [ ] **Step 1: Write the failing tests**

`tests/brain/test_speech.py`:

```python
from pathlib import Path
from types import SimpleNamespace

from synthia.brain.speech import Speech, split_for_tts


def test_split_for_tts_respects_limit_and_sentences():
    text = "One sentence here. " * 10
    parts = split_for_tts(text.strip(), limit=60)
    assert all(len(p) <= 60 for p in parts)
    assert "".join(p + " " for p in parts).strip() == text.strip()
    assert split_for_tts("short", limit=60) == ["short"]


class FakeSTT:
    def __init__(self):
        self.calls = []

    def recognize(self, config, audio):
        self.calls.append((config, audio))
        alt = SimpleNamespace(transcript="run the morning ritual")
        return SimpleNamespace(results=[SimpleNamespace(alternatives=[alt])])


class FakeTTS:
    def __init__(self):
        self.calls = []

    def synthesize_speech(self, input, voice, audio_config):
        self.calls.append((input.text, voice.name, audio_config.audio_encoding))
        return SimpleNamespace(audio_content=b"OggS" + input.text.encode())


def test_transcribe_ogg_uses_opus_and_hints(tmp_path):
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"OggSfake")
    stt = FakeSTT()
    sp = Speech("en-AU", "en-AU-Neural2-B", ["eventflo", "Barry"], stt_client=stt, tts_client=None)
    assert sp.transcribe_ogg(ogg) == "run the morning ritual"
    config, audio = stt.calls[0]
    assert config.language_code == "en-AU"
    assert config.sample_rate_hertz == 48000
    assert list(config.speech_contexts[0].phrases) == ["eventflo", "Barry"]
    assert audio.content == b"OggSfake"


def test_speak_to_ogg_chunks_and_writes(tmp_path):
    tts = FakeTTS()
    sp = Speech("en-AU", "en-AU-Neural2-B", [], stt_client=None, tts_client=tts)
    long_text = ("Sentence number one is here. " * 200).strip()
    files = sp.speak_to_ogg(long_text, tmp_path)
    assert len(files) >= 2
    assert all(f.suffix == ".ogg" and f.read_bytes().startswith(b"OggS") for f in files)
    assert tts.calls[0][1] == "en-AU-Neural2-B"


def test_transcribe_empty_result_returns_empty(tmp_path):
    class Empty:
        def recognize(self, config, audio):
            return SimpleNamespace(results=[])

    ogg = tmp_path / "n.ogg"
    ogg.write_bytes(b"x")
    sp = Speech("en-AU", "v", [], stt_client=Empty(), tts_client=None)
    assert sp.transcribe_ogg(ogg) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_speech.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'synthia.brain.speech'`

- [ ] **Step 3: Implement speech.py**

```python
"""Speech in and out for the brain: Google Cloud STT/TTS, Opus ogg both ways."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TELEGRAM_OPUS_RATE = 48000
TTS_CHUNK_LIMIT = 3000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_for_tts(text: str, limit: int = TTS_CHUNK_LIMIT) -> list[str]:
    """Split on sentence ends so each chunk is at most `limit` characters."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


class Speech:
    def __init__(
        self,
        language: str,
        voice: str,
        phrase_hints: list[str],
        stt_client: Any | None = None,
        tts_client: Any | None = None,
    ) -> None:
        self.language = language
        self.voice = voice
        self.phrase_hints = list(phrase_hints)
        self._stt = stt_client
        self._tts = tts_client

    # ---- lazy real clients ----

    def _stt_client(self) -> Any:
        if self._stt is None:
            from google.cloud import speech

            self._stt = speech.SpeechClient()
        return self._stt

    def _tts_client(self) -> Any:
        if self._tts is None:
            from google.cloud import texttospeech

            self._tts = texttospeech.TextToSpeechClient()
        return self._tts

    # ---- STT ----

    def transcribe_ogg(self, path: Path) -> str:
        from google.cloud import speech

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=TELEGRAM_OPUS_RATE,
            language_code=self.language,
            enable_automatic_punctuation=True,
            speech_contexts=[speech.SpeechContext(phrases=self.phrase_hints)],
        )
        audio = speech.RecognitionAudio(content=path.read_bytes())
        response = self._stt_client().recognize(config=config, audio=audio)
        text = " ".join(
            r.alternatives[0].transcript for r in response.results if r.alternatives
        ).strip()
        logger.info("Transcribed %d chars", len(text))
        return text

    # ---- TTS ----

    def speak_to_ogg(self, text: str, out_dir: Path) -> list[Path]:
        from google.cloud import texttospeech

        out_dir.mkdir(parents=True, exist_ok=True)
        voice = texttospeech.VoiceSelectionParams(
            language_code="-".join(self.voice.split("-")[:2]), name=self.voice
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.OGG_OPUS
        )
        files: list[Path] = []
        for chunk in split_for_tts(text):
            response = self._tts_client().synthesize_speech(
                input=texttospeech.SynthesisInput(text=chunk),
                voice=voice,
                audio_config=audio_config,
            )
            path = out_dir / f"{uuid.uuid4().hex}.ogg"
            path.write_bytes(response.audio_content)
            files.append(path)
        return files
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_speech.py -v`
Expected: 4 PASS (the Google libraries are installed in the venv via the `brain` extra; only their message classes are used in tests, no network).

- [ ] **Step 5: Smoke test with a real note (needs Google credentials)**

```bash
source venv/bin/activate
python - <<'EOF'
from pathlib import Path
from synthia.brain.speech import Speech
sp = Speech("en-AU", "en-AU-Neural2-B", ["eventflo", "Barry"])
files = sp.speak_to_ogg("Morning Mark. Barry ready for his walk?", Path("/tmp/claude-1000/brain-smoke"))
print(files)
print(repr(sp.transcribe_ogg(files[0])))
EOF
```

Expected: one ogg file written, transcript close to the spoken sentence. If `GOOGLE_APPLICATION_CREDENTIALS` is unset, export the same path Synthia's config uses (`google_credentials` in `~/.config/synthia/config.yaml`).

- [ ] **Step 6: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/speech.py tests/brain/test_speech.py
git commit -m "feat(brain): Google speech in and out as Opus ogg"
```

---

### Task 9: Telegram transport

**Files:**
- Modify: `src/synthia/brain/transports/telegram.py` (replace placeholder)
- Create: `tests/brain/test_telegram.py`

**Interfaces:**
- Consumes: `Brain` (`send`, `events`, `interrupt`, `new_session`, `jobs.list_jobs()`), `Speech`, `BrainConfig`.
- Produces:
  - `TelegramTransport(brain, speech, allowed_users: list[int], chat_id: int | None, confirm_timeout_s: int, work_dir: Path)` with async handlers `on_voice(update, context)`, `on_text(update, context)`, `on_stop`, `on_new`, `on_jobs`, plus `async confirm(question: str) -> bool` (the `Confirmer` passed into `Brain`), `async pump_events(bot)`, and `build_app(token) -> Application`.
  - `run_telegram(cfg: BrainConfig) -> int`.

Confirmation flow: `confirm()` speaks the question as a voice note to `chat_id`, creates an `asyncio.Future`, and waits up to `confirm_timeout_s`. While a future is pending, the next incoming text or transcribed voice message resolves it (`True` if the text contains a standalone "yes"/"yep"/"confirm"/"go ahead", else `False`) instead of going to the brain.

- [ ] **Step 1: Write the failing tests**

`tests/brain/test_telegram.py`:

```python
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from synthia.brain.jobs import JobRecord
from synthia.brain.transports.telegram import TelegramTransport, is_yes


class FakeBrain:
    def __init__(self):
        self.sent = []
        self.interrupts = 0
        self.new_sessions = 0
        self._events: asyncio.Queue = asyncio.Queue()
        self.jobs = SimpleNamespace(list_jobs=lambda: [])

    async def send(self, text):
        self.sent.append(text)
        yield "reply to "
        yield text

    async def interrupt(self):
        self.interrupts += 1

    async def new_session(self, handover=None):
        self.new_sessions += 1

    async def events(self):
        while True:
            yield await self._events.get()


class FakeSpeech:
    def __init__(self):
        self.spoken = []

    def transcribe_ogg(self, path):
        return "run the morning ritual"

    def speak_to_ogg(self, text, out_dir):
        self.spoken.append(text)
        p = Path(out_dir) / f"{len(self.spoken)}.ogg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"OggS")
        return [p]


class FakeBot:
    def __init__(self):
        self.voices = []
        self.actions = []
        self.texts = []

    async def send_voice(self, chat_id, voice, caption=None, **kw):
        self.voices.append((chat_id, caption))

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)

    async def send_message(self, chat_id, text, **kw):
        self.texts.append((chat_id, text))


class FakeFile:
    async def download_to_drive(self, path):
        Path(path).write_bytes(b"OggSfake")


class FakeMessage:
    def __init__(self, bot, text=None, voice=False):
        self.text = text
        self.voice = SimpleNamespace(get_file=self._get_file) if voice else None
        self._bot = bot

    async def _get_file(self):
        return FakeFile()

    async def reply_text(self, text, **kw):
        self._bot.texts.append((1, text))


def _update(user_id=1, text=None, voice=False, bot=None):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=1),
        message=FakeMessage(bot, text=text, voice=voice),
    )


@pytest.fixture
def parts(tmp_path):
    brain, speech, bot = FakeBrain(), FakeSpeech(), FakeBot()
    tr = TelegramTransport(brain, speech, allowed_users=[1], chat_id=1, confirm_timeout_s=1, work_dir=tmp_path)
    ctx = SimpleNamespace(bot=bot)
    return brain, speech, bot, tr, ctx


def test_is_yes():
    assert is_yes("yes")
    assert is_yes("Yep go for it")
    assert is_yes("confirm")
    assert not is_yes("no")
    assert not is_yes("yesterday was fine")


async def test_voice_roundtrip(parts):
    brain, speech, bot, tr, ctx = parts
    await tr.on_voice(_update(voice=True, bot=bot), ctx)
    assert brain.sent == ["run the morning ritual"]
    assert speech.spoken == ["reply to run the morning ritual"]
    assert bot.voices[-1][1] == "reply to run the morning ritual"
    assert bot.actions  # typing/recording chat actions were sent


async def test_unauthorised_ignored(parts):
    brain, speech, bot, tr, ctx = parts
    await tr.on_text(_update(user_id=99, text="hi", bot=bot), ctx)
    assert brain.sent == []
    assert bot.voices == [] and bot.texts == []


async def test_commands(parts):
    brain, speech, bot, tr, ctx = parts
    await tr.on_stop(_update(text="/stop", bot=bot), ctx)
    await tr.on_new(_update(text="/new", bot=bot), ctx)
    await tr.on_jobs(_update(text="/jobs", bot=bot), ctx)
    assert brain.interrupts == 1
    assert brain.new_sessions == 1
    assert any("No jobs" in t for _, t in bot.texts)


async def test_confirm_yes_and_timeout(parts):
    brain, speech, bot, tr, ctx = parts
    tr.bot = bot
    task = asyncio.create_task(tr.confirm("run git push origin main"))
    await asyncio.sleep(0.01)
    assert speech.spoken[-1].startswith("I want to run git push origin main")
    await tr.on_text(_update(text="yes do it", bot=bot), ctx)
    assert await task is True
    assert brain.sent == []  # the yes did not go to the brain

    task = asyncio.create_task(tr.confirm("run gh pr merge 1"))
    assert await asyncio.wait_for(task, 3) is False  # timed out (confirm_timeout_s=1)


async def test_pump_events_pushes_voice(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done, two meetings today."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert bot.voices[-1] == (1, "Briefing is done, two meetings today.")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/brain/test_telegram.py -v`
Expected: FAIL with `ImportError: cannot import name 'TelegramTransport'`

- [ ] **Step 3: Implement transports/telegram.py**

```python
"""Telegram transport: voice notes in, voice notes out, job events pushed."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from synthia.brain.config import BrainConfig

logger = logging.getLogger(__name__)

_YES = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|go ahead|do it|approved)\b", re.IGNORECASE)


def is_yes(text: str) -> bool:
    return bool(_YES.search(text or ""))


class TelegramTransport:
    def __init__(
        self,
        brain: Any,
        speech: Any,
        allowed_users: list[int],
        chat_id: int | None,
        confirm_timeout_s: int,
        work_dir: Path,
    ) -> None:
        self.brain = brain
        self.speech = speech
        self.allowed_users = set(allowed_users)
        self.chat_id = chat_id
        self.confirm_timeout_s = confirm_timeout_s
        self.work_dir = work_dir
        self.bot: Any = None
        self._pending_confirm: asyncio.Future[bool] | None = None

    # ---- helpers ----

    def _authorised(self, update: Any) -> bool:
        user = getattr(update, "effective_user", None)
        return user is not None and user.id in self.allowed_users

    async def _speak(self, bot: Any, chat_id: int, text: str) -> None:
        if not text.strip():
            return
        try:
            files = await asyncio.to_thread(self.speech.speak_to_ogg, text, self.work_dir / "out")
        except Exception as e:
            logger.error("TTS failed: %s", e)
            await bot.send_message(chat_id=chat_id, text=text)
            return
        for i, path in enumerate(files):
            with open(path, "rb") as f:
                await bot.send_voice(chat_id=chat_id, voice=f, caption=text if i == 0 else None)
            path.unlink(missing_ok=True)

    async def _handle_text(self, update: Any, context: Any, text: str) -> None:
        chat_id = update.effective_chat.id
        if self.chat_id is None:
            self.chat_id = chat_id
        if self._pending_confirm is not None and not self._pending_confirm.done():
            self._pending_confirm.set_result(is_yes(text))
            return
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        t0 = time.monotonic()
        chunks = [c async for c in self.brain.send(text)]
        reply = "".join(chunks).strip()
        logger.info("turn: in=%d chars out=%d chars %.1fs", len(text), len(reply), time.monotonic() - t0)
        await self._speak(context.bot, chat_id, reply or "I did not get a reply. Try again?")

    # ---- handlers ----

    async def on_text(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message or not update.message.text:
            return
        await self._handle_text(update, context, update.message.text.strip())

    async def on_voice(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message or not update.message.voice:
            return
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        tg_file = await update.message.voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", dir=self.work_dir, delete=False) as f:
            ogg_path = Path(f.name)
        try:
            await tg_file.download_to_drive(str(ogg_path))
            try:
                text = await asyncio.to_thread(self.speech.transcribe_ogg, ogg_path)
            except Exception as e:
                logger.error("STT failed: %s", e)
                await update.message.reply_text("Cloud speech is down. Type it instead?")
                return
        finally:
            ogg_path.unlink(missing_ok=True)
        if not text:
            await update.message.reply_text("Couldn't make that out. Say it again?")
            return
        await self._handle_text(update, context, text)

    async def on_stop(self, update: Any, context: Any) -> None:
        if not self._authorised(update):
            return
        await self.brain.interrupt()
        await update.message.reply_text("Stopped.")

    async def on_new(self, update: Any, context: Any) -> None:
        if not self._authorised(update):
            return
        await self.brain.new_session()
        await update.message.reply_text("Fresh session.")

    async def on_jobs(self, update: Any, context: Any) -> None:
        if not self._authorised(update):
            return
        jobs = self.brain.jobs.list_jobs()
        text = "No jobs." if not jobs else "\n".join(f"{j.name}: {j.status}" for j in jobs)
        await update.message.reply_text(text)

    # ---- confirmation (Confirmer for the brain's gate) ----

    async def confirm(self, question: str) -> bool:
        if self.bot is None or self.chat_id is None:
            logger.warning("confirm requested with no chat; denying: %s", question)
            return False
        loop = asyncio.get_running_loop()
        self._pending_confirm = loop.create_future()
        await self._speak(self.bot, self.chat_id, f"I want to {question}. Say yes to confirm.")
        try:
            return await asyncio.wait_for(self._pending_confirm, self.confirm_timeout_s)
        except asyncio.TimeoutError:
            await self._speak(self.bot, self.chat_id, "No confirmation, so I did not do it.")
            return False
        finally:
            self._pending_confirm = None

    # ---- job events ----

    async def pump_events(self, bot: Any) -> None:
        async for ev in self.brain.events():
            if self.chat_id is None:
                logger.warning("job event with no chat id; dropping %s", ev.job.id)
                continue
            await self._speak(bot, self.chat_id, ev.text or f"{ev.job.name} finished.")

    # ---- wiring ----

    def build_app(self, token: str) -> Application:
        app = Application.builder().token(token).post_init(self._post_init).build()
        app.add_handler(CommandHandler("stop", self.on_stop))
        app.add_handler(CommandHandler("new", self.on_new))
        app.add_handler(CommandHandler("jobs", self.on_jobs))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.VOICE, self.on_voice))
        return app

    async def _post_init(self, app: Application) -> None:
        self.bot = app.bot
        await self.brain.start()
        app.create_task(self.pump_events(app.bot))


def run_telegram(cfg: BrainConfig) -> int:
    from synthia.brain.cli import pull_repos
    from synthia.brain.concierge import Brain
    from synthia.brain.speech import Speech

    if not cfg.telegram_token:
        print("BRAIN_TELEGRAM_TOKEN is not set")
        return 2
    pull_repos(cfg.repos)
    work_dir = cfg.state_dir / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    speech = Speech(cfg.language, cfg.voice, cfg.phrase_hints)
    transport = TelegramTransport(
        brain=None,
        speech=speech,
        allowed_users=cfg.telegram_allowed_users,
        chat_id=cfg.telegram_chat_id,
        confirm_timeout_s=cfg.confirm_timeout_s,
        work_dir=work_dir,
    )
    transport.brain = Brain(cfg, transport.confirm)
    app = transport.build_app(cfg.telegram_token)
    logger.info("Synthia brain listening on Telegram")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/brain/test_telegram.py -v`
Expected: 6 PASS. The fake `Update` objects only need the attributes the handlers touch; if a handler reads an attribute the fake lacks, add it to `_update()` rather than loosening the handler.

- [ ] **Step 5: Quality gates and commit**

```bash
black src/synthia/brain tests/brain && isort src/synthia/brain tests/brain
mypy src/synthia/ --ignore-missing-imports && pytest tests/ -q
git add src/synthia/brain/transports/telegram.py tests/brain/test_telegram.py
git commit -m "feat(brain): Telegram voice transport with confirmation and job push"
```

---

### Task 10: Deployment files for middo247

**Files:**
- Create: `deploy/brain/synthia-brain.service`, `deploy/brain/eventflo-pull.service`, `deploy/brain/eventflo-pull.timer`, `deploy/brain/brain.env.example`, `deploy/brain/brain.yaml.example`, `deploy/brain/install.sh`, `deploy/brain/syncthing-folders.md`

**Interfaces:**
- Consumes: `synthia-brain telegram` (Task 7/9), `BrainConfig` keys (Task 2).

- [ ] **Step 1: Write the systemd units**

`deploy/brain/synthia-brain.service`:

```ini
[Unit]
Description=Synthia mobile voice brain (Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=markmiddo
WorkingDirectory=/home/markmiddo/dev/misc/synthia
EnvironmentFile=/home/markmiddo/.config/synthia/brain.env
Environment=PATH=/home/markmiddo/.local/bin:/home/markmiddo/.npm-global/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/markmiddo/dev/misc/synthia/venv/bin/synthia-brain telegram
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

`deploy/brain/eventflo-pull.service`:

```ini
[Unit]
Description=Fast-forward pull of eventflo repos for the Synthia brain

[Service]
Type=oneshot
User=markmiddo
ExecStart=/bin/bash -c 'for r in /home/markmiddo/dev/eventflo/*/; do [ -d "$r/.git" ] && git -C "$r" pull --ff-only || true; done'
```

`deploy/brain/eventflo-pull.timer`:

```ini
[Unit]
Description=Pull eventflo repos every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Write the config examples**

`deploy/brain/brain.env.example`:

```bash
# Copy to ~/.config/synthia/brain.env, chmod 600. Never commit the real file.
BRAIN_TELEGRAM_TOKEN=123456:replace-me
GOOGLE_APPLICATION_CREDENTIALS=/home/markmiddo/.config/synthia/google-credentials.json
```

`deploy/brain/brain.yaml.example`:

```yaml
# Copy to ~/.config/synthia/brain.yaml
cwd: ~/dev/eventflo
repos:
  - ~/dev/eventflo/eva-ai
  - ~/dev/eventflo/eva-core
  - ~/dev/eventflo/admin-panel
language: en-AU
voice: en-AU-Neural2-B
phrase_hints: [eventflo, Eva, Eva Core, Barry, FloSale, Vishal, Corey]
telegram_allowed_users: [111111111]
telegram_chat_id: 111111111
max_workers: 2
job_timeout_s: 1800
confirm_timeout_s: 120
```

- [ ] **Step 3: Write install.sh and the Syncthing notes**

`deploy/brain/install.sh`:

```bash
#!/usr/bin/env bash
# Install or update the Synthia brain on this machine (run on middo247 as markmiddo).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -e ".[dev,brain]"
mkdir -p ~/.config/systemd/user ~/.config/synthia
cp deploy/brain/synthia-brain.service deploy/brain/eventflo-pull.service deploy/brain/eventflo-pull.timer ~/.config/systemd/user/
[ -f ~/.config/synthia/brain.env ] || { cp deploy/brain/brain.env.example ~/.config/synthia/brain.env; chmod 600 ~/.config/synthia/brain.env; echo "Edit ~/.config/synthia/brain.env"; }
[ -f ~/.config/synthia/brain.yaml ] || cp deploy/brain/brain.yaml.example ~/.config/synthia/brain.yaml
systemctl --user daemon-reload
systemctl --user enable --now eventflo-pull.timer
systemctl --user enable synthia-brain.service
systemctl --user restart synthia-brain.service
loginctl enable-linger "$USER" >/dev/null 2>&1 || true
echo "Done. Logs: journalctl --user -u synthia-brain -f"
```

`deploy/brain/syncthing-folders.md`:

```markdown
# Syncthing folders: desktop <-> middo247

Install `syncthing` on both machines (`sudo apt install syncthing`, `systemctl --user enable --now syncthing`).
Pair the devices in the web UI (http://localhost:8384) once. Then share these folders, both directions,
same path on both machines:

| Folder ID | Path |
|-----------|------|
| claude-skills | ~/.claude/skills |
| claude-agents | ~/.claude/agents |
| claude-plugins | ~/.claude/plugins |
| claude-eventflo-memory | ~/.claude/projects/-home-markmiddo-dev-eventflo/memory |
| claude-root-files | ~/.claude (see ignore list below; only settings.json and CLAUDE.md pass) |

`.stignore` for `claude-root-files`:

    !settings.json
    !CLAUDE.md
    *

Never sync: `~/.claude/projects/*/` transcripts, `.credentials.json`, `statsig`, caches, `*.bak*`.
Secrets (`.mcp.json` keys, Google credentials, bot token) are copied by hand into
`~/.config/synthia/brain.env` on the server.
```

- [ ] **Step 4: Verify units parse and script runs a dry pass**

```bash
chmod +x deploy/brain/install.sh
systemd-analyze --user verify deploy/brain/synthia-brain.service deploy/brain/eventflo-pull.service deploy/brain/eventflo-pull.timer
bash -n deploy/brain/install.sh
```

Expected: no output from verify (warnings about missing EnvironmentFile on the desktop are fine), `bash -n` silent.

- [ ] **Step 5: Commit**

```bash
git add deploy/brain
git commit -m "chore(brain): systemd units, timer, config examples and install script"
```

---

### Task 11: Operator doc and CLAUDE.md pointer

**Files:**
- Create: `docs/brain.md`
- Modify: `CLAUDE.md` (Key Directories list: add `src/synthia/brain/` and `deploy/brain/`; Running Synthia: add `synthia-brain repl` and `synthia-brain telegram`)

- [ ] **Step 1: Write docs/brain.md**

```markdown
# Synthia Brain (mobile voice)

The brain is a long-lived Claude Agent SDK session running in `~/dev/eventflo` on middo247,
talking to Mark over Telegram voice notes. Design: `docs/superpowers/specs/2026-09-09-mobile-voice-brain-design.md`.

## Authentication

<Result of Task 1 goes here: "Runs on the Claude Max login, no API key needed" or
"Requires ANTHROPIC_API_KEY in brain.env; model default set to <model>". Replace this line.>

## Install on middo247

    git clone git@github.com:markmiddo/synthia.git ~/dev/misc/synthia   # once
    cd ~/dev/misc/synthia && git pull && deploy/brain/install.sh
    nano ~/.config/synthia/brain.env     # bot token, Google credentials path
    nano ~/.config/synthia/brain.yaml    # allowed user id, chat id, repos
    systemctl --user restart synthia-brain

Prerequisites on the server: `claude` CLI logged in (`claude login`), eventflo repos cloned under
`~/dev/eventflo`, Syncthing folders shared per `deploy/brain/syncthing-folders.md` (this also brings
`~/.claude/settings.json` with the security-gate PreToolUse hook that workers rely on).

## Run from the desktop (text only)

    synthia-brain repl -v

Drive the same brain from the keyboard. `/stop`, `/new`, `/jobs`, `/quit`.

## Telegram commands

`/stop` interrupts the current reply. `/new` starts a fresh session (handover is not carried).
`/jobs` lists background jobs. Anything else, voice or text, goes to the brain.

## How it behaves

- Quick things are answered inline. Long things ("run the morning ritual") are dispatched as
  background workers; you get a voice note when they finish.
- Risky tool calls (git push, PR merge, service restarts, database writes) are read out and need a
  spoken "yes" within two minutes, otherwise denied.
- A new session starts each day with a five-line handover from the previous one.

## Troubleshooting

    journalctl --user -u synthia-brain -f          # live log
    ls ~/.local/share/synthia/brain/jobs/           # job records and worker logs
    cat ~/.local/share/synthia/brain/session.json   # current session id and date

"Cloud speech is down": Google credentials missing or expired in `brain.env`.
No replies at all: check `telegram_allowed_users` matches your Telegram user id.
Worker fails instantly: run `claude -p "hi" --output-format json` in `~/dev/eventflo` on the server.
```

- [ ] **Step 2: Update CLAUDE.md**

In "Key Directories" add:

```
- `src/synthia/brain/` - mobile voice brain (Agent SDK concierge, job workers, Telegram transport); see `docs/brain.md`
- `deploy/brain/` - systemd units and install script for the brain on middo247
```

In "Running Synthia" add:

```
synthia-brain repl      # Text REPL against the voice brain (desktop testing)
synthia-brain telegram  # Telegram voice transport (runs on middo247)
```

- [ ] **Step 3: Fill in the Authentication section from Task 1's finding**, then commit

```bash
git add docs/brain.md CLAUDE.md
git commit -m "docs(brain): operator guide and CLAUDE.md pointers"
```

---

### Task 12: First walk (manual integration)

**Files:** none.

- [ ] **Step 1: Deploy**

```bash
git push origin development
ssh server "cd ~/dev/misc/synthia && git pull && deploy/brain/install.sh"
ssh server "journalctl --user -u synthia-brain -n 20 --no-pager"
```

Expected: log line "Synthia brain listening on Telegram".

- [ ] **Step 2: Round trip**

Send a voice note: "what's on today". Expect a voice note reply within twenty seconds with the reply text as caption.

- [ ] **Step 3: Job round trip**

Send: "run the morning ritual". Expect an immediate "on it" voice note, then a second voice note when `/morning` finishes. Check `ls ~/.local/share/synthia/brain/jobs/` on the server shows the record with `"status": "done"`.

- [ ] **Step 4: Confirmation path**

Send text: "push the development branch of synthia". Expect a voice note "I want to run git push ... Say yes to confirm." Reply "no". Expect the brain to report it did not push.

- [ ] **Step 5: Record findings**

Note latency and any transcript misses in `docs/brain.md` Troubleshooting. Commit with `docs(brain): first-walk notes`.
