import asyncio
import json
import os
from pathlib import Path

from synthia.brain.concierge import Brain
from synthia.brain.config import BrainConfig
from synthia.brain.fleet_context import FleetContext, read_subagents, wrap_context

from .test_concierge import FakeClient, _cfg, _collect, _result, _yes  # noqa: F401

NOW = 1_800_000_000.0


def _agent(pane, title, status, cwd, session="", kind="claude"):
    return {
        "pane_id": pane,
        "agent": kind,
        "agent_status": status,
        "cwd": cwd,
        "terminal_title_stripped": title,
        "agent_session": {"value": session} if session else {},
    }


def _snap(*agents) -> str:
    return json.dumps({"result": {"snapshot": {"agents": list(agents)}}})


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


def _ctx(tmp_path, raw, clock=None, calls=None):
    clock = clock or Clock()

    async def snap():
        if calls is not None:
            calls.append(1)
        if isinstance(raw, Exception):
            raise raw
        return raw

    return FleetContext(
        snapshot=snap, projects_root=tmp_path / "projects", home=tmp_path, clock=clock, mono=clock
    )


def _sub(tmp_path, cwd, session, sid, desc, age):
    d = tmp_path / "projects" / cwd.replace("/", "-").replace(".", "-") / session / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.meta.json").write_text(json.dumps({"description": desc}))
    j = d / f"{sid}.jsonl"
    j.write_text("{}")
    os.utime(j, (NOW - age, NOW - age))


async def test_formats_and_orders_needs_you_first(tmp_path):
    home = str(tmp_path)
    raw = _snap(
        _agent("p1", "Idle thing", "idle", f"{home}/dev/personal"),
        _agent("p2", "Admin panel", "working", f"{home}/dev/eventflo/eventflo-app", "s2"),
        _agent("p3", "Stuck one", "blocked", f"{home}/dev/misc/synthia"),
    )
    _sub(tmp_path, f"{home}/dev/eventflo/eventflo-app", "s2", "a1", "Unlock fix", 10)
    _sub(tmp_path, f"{home}/dev/eventflo/eventflo-app", "s2", "a2", "Old one", 600)
    _sub(tmp_path, f"{home}/dev/eventflo/eventflo-app", "s2", "a3", "Older one", 900)
    out = await _ctx(tmp_path, raw).summary()
    lines = out.splitlines()
    assert lines[0].startswith("[Live agents at ")
    assert lines[1] == "Stuck one (synthia): NEEDS YOU."
    assert lines[2] == ("Admin panel (eventflo-app): working; live sub-agents: Unlock fix; 2 done.")
    assert lines[3] == "Idle thing (personal): idle."


async def test_state_age_from_tracker_and_transcript(tmp_path):
    home = str(tmp_path)
    cwd = f"{home}/dev/personal"
    proj = tmp_path / "projects" / cwd.replace("/", "-").replace(".", "-")
    proj.mkdir(parents=True)
    t = proj / "sid.jsonl"
    t.write_text("{}")
    os.utime(t, (NOW - 960, NOW - 960))
    clock = Clock()
    raw = _snap(
        _agent("p1", "Visa", "idle", cwd, "sid"),
        _agent("p2", "Build", "working", f"{home}/dev/x"),
    )
    ctx = _ctx(tmp_path, raw, clock)
    first = await ctx.summary()
    assert "Visa (personal): idle 16m." in first
    assert "Build (x): working." in first
    clock.t += 5 * 60
    again = await ctx.summary()
    assert "Build (x): working 5m." in again


async def test_caps_at_twelve_lines(tmp_path):
    agents = [_agent(f"p{i}", f"Agent {i}", "working", f"{tmp_path}/dev/r{i}") for i in range(30)]
    out = await _ctx(tmp_path, _snap(*agents)).summary()
    lines = out.splitlines()
    assert len(lines) == 12
    assert lines[-1] == "plus 20 more agents"


async def test_caches_for_three_seconds(tmp_path):
    calls: list[int] = []
    clock = Clock()
    ctx = _ctx(tmp_path, _snap(_agent("p1", "A", "idle", "/x")), clock, calls)
    await ctx.summary()
    clock.t += 2
    await ctx.summary()
    assert len(calls) == 1
    clock.t += 2
    await ctx.summary()
    assert len(calls) == 2


async def test_failures_return_empty(tmp_path):
    assert await _ctx(tmp_path, RuntimeError("boom")).summary() == ""
    assert await _ctx(tmp_path, "{not json").summary() == ""
    assert await _ctx(tmp_path, json.dumps({"result": {}})).summary() == ""
    assert await _ctx(tmp_path, _snap()).summary() == ""


async def test_herdr_timeout_returns_empty(tmp_path, monkeypatch):
    from synthia.brain import fleet_context

    async def slow(*a, **k):
        await asyncio.sleep(10)

    monkeypatch.setattr(fleet_context, "HERDR_TIMEOUT_S", 0.05)
    real = fleet_context.run_herdr_snapshot

    async def fake_exec(*a, **k):
        class P:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(10)

            def kill(self):
                self.returncode = -9

            async def wait(self):
                return -9

        return P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    ctx = FleetContext(snapshot=lambda: real(0.05), projects_root=tmp_path, home=tmp_path)
    assert await ctx.summary() == ""


def test_read_subagents_rejects_hostile_session(tmp_path):
    assert read_subagents(tmp_path, "/p", "../x", NOW) == []
    assert read_subagents(tmp_path, "/p", "", NOW) == []
    assert read_subagents(tmp_path, "/p", "missing", NOW) == []


def test_wrap_context():
    assert wrap_context("") == ""
    assert wrap_context("X").startswith("[context, not from Mark] X")
    assert wrap_context("X").endswith("[Mark said] ")


class _Fleet:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    async def summary(self):
        self.calls += 1
        return self.text


async def test_injected_for_desk_and_telegram_not_for_job_events(tmp_path):
    fleet = _Fleet("[Live agents at 10:00]\nA (r): working.")
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None, fleet=fleet)
    await brain.start()
    await _collect(brain.send("what is going on", origin="desk"))
    desk = FakeClient.instances[-1].queries[-1]
    assert desk.startswith("[desk] [context, not from Mark] [Live agents at 10:00]")
    assert desk.endswith("[Mark said] what is going on")
    await _collect(brain.send("status?", origin="telegram"))
    tg = FakeClient.instances[-1].queries[-1]
    assert tg.startswith("[context, not from Mark] ")
    assert tg.endswith("[Mark said] status?")
    assert fleet.calls == 2
    await _collect(brain.send("plain"))  # no origin: housekeeping, no block
    assert FakeClient.instances[-1].queries[-1] == "plain"
    assert fleet.calls == 2
    # the journal keeps Mark's words only
    journal = "".join(p.read_text() for p in (tmp_path / "walk").rglob("*.md"))
    assert "context, not from Mark" not in journal
    await brain.stop()


async def test_job_event_turns_get_no_block(tmp_path):
    fleet = _Fleet("BLOCK")
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None, fleet=fleet)
    await brain.start()
    await brain._ask("[job event] x finished (done): ok")
    assert FakeClient.instances[-1].queries[-1] == "[job event] x finished (done): ok"
    assert fleet.calls == 0
    await brain.stop()


async def test_empty_summary_leaves_prompt_unchanged(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None, fleet=_Fleet(""))
    await brain.start()
    await _collect(brain.send("hi", origin="desk"))
    assert FakeClient.instances[-1].queries[-1] == "[desk] hi"
    await brain.stop()
