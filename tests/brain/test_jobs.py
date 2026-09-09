import asyncio
import json
import os
import time
from datetime import datetime, timedelta

import pytest

from synthia.brain.jobs import (
    JobFinished,
    JobManager,
    JobRecord,
    JobStore,
    claude_runner,
    summarize,
)


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


def test_summarize_non_object_json():
    ok, summary = summarize("42")
    assert ok is False
    assert summary == "42"
    ok, summary = summarize('["a"]')
    assert ok is False
    assert summary == '["a"]'


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


async def test_runner_exception_marks_failed(tmp_path):
    events: asyncio.Queue[JobFinished] = asyncio.Queue()

    async def runner(rec):
        raise FileNotFoundError("claude")

    mgr = JobManager(JobStore(tmp_path), events, runner, max_workers=2, timeout_s=5)
    rec = await mgr.dispatch("test", "prompt")
    ev = await asyncio.wait_for(events.get(), 2)
    assert ev.job.status == "failed"
    assert ev.job.ok is False
    assert "crashed" in ev.job.summary
    assert mgr.status(rec.id).status == "failed"
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


async def test_claude_runner_builds_command(tmp_path, monkeypatch):
    """The worker subprocess gets the worker allowlist, acceptEdits and the job cwd."""
    captured: dict = {}

    class FakeProc:
        pid = 4321
        returncode = 0

        async def communicate(self):
            return b'{"is_error": false, "result": "ok"}', b""

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    tools = ["Bash", "Read", "mcp__eva-core__*"]
    run = claude_runner(tmp_path, tools)
    rec = JobRecord(id="j1", name="morning", prompt="/morning", started="t")
    code, out, err = await run(rec)

    assert (code, err) == (0, "")
    assert json.loads(out)["result"] == "ok"
    assert rec.pid == 4321

    cmd = captured["cmd"]
    assert cmd[0] == "claude"
    assert cmd[1] == "-p"
    assert cmd[2] == "/morning"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash,Read,mcp__eva-core__*"
    assert captured["kwargs"]["cwd"] == str(tmp_path)


def test_prune_removes_old_records_and_logs(tmp_path):
    store = JobStore(tmp_path / "jobs")
    old_started = (datetime.now() - timedelta(days=30)).replace(microsecond=0).isoformat()
    new_started = datetime.now().replace(microsecond=0).isoformat()
    store.save(JobRecord(id="old", name="stale", prompt="p", started=old_started))
    store.save(JobRecord(id="new", name="fresh", prompt="p", started=new_started))
    old_log = store.root / "old.log"
    new_log = store.root / "new.log"
    old_log.write_text("old output")
    new_log.write_text("new output")
    stale = time.time() - 30 * 86400
    os.utime(old_log, (stale, stale))

    assert store.prune(max_age_days=14) == 2
    assert not (store.root / "old.json").exists()
    assert not old_log.exists()
    assert (store.root / "new.json").exists()
    assert new_log.exists()
    assert [r.id for r in store.list_all()] == ["new"]
