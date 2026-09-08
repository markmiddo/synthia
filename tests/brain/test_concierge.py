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
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": word + " "},
                },
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
