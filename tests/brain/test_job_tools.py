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
