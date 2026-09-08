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
