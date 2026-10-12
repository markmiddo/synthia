import asyncio
from datetime import date

import pytest

from synthia.brain import herdr_tools
from synthia.brain.concierge import Brain
from synthia.brain.config import BrainConfig
from synthia.brain.squad_events import event_record, run_squad_tail
from synthia.squads.engine import Engine
from synthia.squads.events import EventTail
from tests.fake_herdr import FakeHerdr, write_squad


@pytest.fixture
def env(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    write_squad(tmp_path / "cfg", work)
    fake = FakeHerdr()
    eng = Engine(tmp_path / "data", tmp_path / "cfg", fake, today=lambda: date(2026, 10, 13))
    tools = {t.name: t for t in herdr_tools.make_tools(eng)}
    return eng, fake, tools, tmp_path


def text(result):
    return result["content"][0]["text"]


async def test_tool_names():
    names = {t.name for t in herdr_tools.make_tools(Engine(herdr=FakeHerdr()))}
    assert names == {
        "fleet", "open_agent", "prompt_agent", "read_agent", "close_agent",
        "start_squad", "squad_status", "stop_squad",
    }  # fmt: skip


async def test_start_squad_status_and_fleet(env):
    eng, fake, tools, _ = env
    out = await tools["start_squad"].handler({"squad": "growth", "brief": "Three posts"})
    assert "growth-director is briefed" in text(out)
    st = text(await tools["squad_status"].handler({}))
    assert "working" in st and "growth-director" in st
    fl = text(await tools["fleet"].handler({}))
    assert "growth-director: Marketing Director" in fl and "growth squad growth-director" in fl
    out = await tools["stop_squad"].handler({"job": "2026-10-13-three-posts"})
    assert "Stopped growth-director" in text(out)


async def test_unknown_squad_reports_error(env):
    out = await env[2]["start_squad"].handler({"squad": "zzz", "brief": "b"})
    assert out["is_error"] and "no squad" in text(out)


async def test_close_agent_refuses_unregistered(env):
    eng, fake, tools, _ = env
    fake.panes["w1:p50"] = {"name": "marks-agent", "cwd": "/x"}
    out = await tools["close_agent"].handler({"name": "marks-agent"})
    assert out["is_error"] and "won't close" in text(out)
    assert "w1:p50" in fake.panes


async def test_open_prompt_read_close(env):
    eng, fake, tools, tmp = env
    out = await tools["open_agent"].handler(
        {"name": "helper", "cwd": str(tmp), "prompt": "go", "model": ""}
    )
    assert "helper is open" in text(out)
    assert not (await tools["prompt_agent"].handler({"name": "helper", "text": "more"})).get(
        "is_error"
    )
    assert "output of helper" in text(await tools["read_agent"].handler({"name": "helper"}))
    assert "closed" in text(await tools["close_agent"].handler({"name": "helper"}))


def test_brain_registers_herdr_server_and_gates_it(tmp_path):
    cfg = BrainConfig(state_dir=tmp_path / "state", journal_dir=tmp_path / "j", cwd=tmp_path)
    brain = Brain(
        cfg, confirm=None, client_factory=lambda o: None, squads=Engine(herdr=FakeHerdr())
    )
    opts = brain._options(None, None)
    assert set(opts.mcp_servers) == {"jobs", "herdr"}
    assert "mcp__herdr__close_agent" in opts.allowed_tools


async def test_tail_pushes_events(tmp_path):
    (tmp_path / "e.jsonl").write_text(
        '{"squad": "growth", "job": "2026-10-13-posts", "text": "Growth posts are ready for review"}\n'
    )
    got = []
    task = asyncio.create_task(
        run_squad_tail(EventTail(tmp_path / "e.jsonl", tmp_path / "off"), got.append, 0.01)
    )
    for _ in range(100):
        if got:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert got and got[0].summary == "Growth posts are ready for review"
    assert got[0].status == "review" and got[0].name.startswith("growth squad")
    assert event_record({}).summary


def test_event_record_carries_the_directors_summary():
    rec = event_record(
        {
            "squad": "office",
            "job": "2026-10-13-board-cleanup",
            "text": "Office's board cleanup is ready for review",
            "desk": "/d/office/jobs/x",
            "digest": "# Board cleanup\nSix cards moved to In review.",
        }
    )
    assert "Six cards moved to In review." in rec.summary
    assert rec.summary.startswith("Office's board cleanup is ready for review")
