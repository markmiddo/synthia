import asyncio
import json
from datetime import date

import pytest
from claude_agent_sdk import ResultMessage, StreamEvent

from synthia import inbox
from synthia.brain import concierge as concierge_module
from synthia.brain.concierge import Brain, SpokenEvent
from synthia.brain.config import BrainConfig


def _ev(event: dict) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="sess-1", event=event)


def _text_message(*chunks: str, tool: bool = False) -> list[StreamEvent]:
    """The stream events of one assistant message, optionally ending in a tool call."""
    events = [_ev({"type": "message_start"})]
    events.append(_ev({"type": "content_block_start", "content_block": {"type": "text"}}))
    for c in chunks:
        events.append(
            _ev(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": c},
                }
            )
        )
    events.append(_ev({"type": "content_block_stop"}))
    if tool:
        events.append(_ev({"type": "content_block_start", "content_block": {"type": "tool_use"}}))
        events.append(_ev({"type": "content_block_stop"}))
    events.append(_ev({"type": "message_stop"}))
    return events


def _result(text: str) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="sess-1",
        result=text,
    )


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
        # Guards against interrupt()/receive_response() ever being called while
        # idle (no query sent yet) — that would hang forever against the real SDK.
        if not self.queries:
            await asyncio.Event().wait()
            return
        yield _ev({"type": "message_start"})
        for word in self.reply.split(" "):
            yield StreamEvent(
                uuid="u",
                session_id="sess-1",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": word + " "},
                },
            )
        yield _ev({"type": "message_stop"})
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sess-1",
            result=self.reply,
        )


class ScriptedClient(FakeClient):
    """Replays a list of messages, then a ResultMessage."""

    script: list = []
    final = ""

    async def receive_response(self):
        for m in self.script:
            yield m
        yield _result(self.final)


class BlockingClient:
    """Stand-in whose receive_response blocks mid-stream until the test releases it."""

    instances: list["BlockingClient"] = []

    def __init__(self, options):
        self.options = options
        self.queries: list[str] = []
        self.interrupted = False
        self.connected = False
        self.release = asyncio.Event()
        self.interrupt_calls = 0
        self.receive_response_calls = 0
        BlockingClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def query(self, prompt, session_id="default"):
        self.queries.append(prompt)

    async def interrupt(self):
        self.interrupted = True
        self.interrupt_calls += 1

    async def receive_response(self):
        self.receive_response_calls += 1
        yield StreamEvent(
            uuid="u",
            session_id="sess-1",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hello "},
            },
        )
        yield _ev({"type": "message_stop"})
        await self.release.wait()
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sess-1",
            result="hello there",
        )


class FlakyOnceClient(FakeClient):
    """Raises once on the first [job event] query, then behaves like FakeClient."""

    def __init__(self, options):
        super().__init__(options)
        self._raised = False

    async def query(self, prompt, session_id="default"):
        if prompt.startswith("[job event]") and not self._raised:
            self._raised = True
            raise RuntimeError("transient failure")
        await super().query(prompt, session_id)


class DirtyStreamClient(FakeClient):
    """First receive_response call for a [job event] query yields one delta then
    raises mid-stream; every other call (the drain's own, and any retry) behaves
    like FakeClient. Records call order so a test can assert the drain happened
    before the retry re-queried."""

    def __init__(self, options):
        super().__init__(options)
        self._raised = False
        self.interrupt_calls = 0
        self.call_order: list[str] = []

    async def query(self, prompt, session_id="default"):
        self.call_order.append(f"query:{prompt}")
        await super().query(prompt, session_id)

    async def interrupt(self):
        self.call_order.append("interrupt")
        self.interrupt_calls += 1
        await super().interrupt()

    async def receive_response(self):
        if self.queries[-1].startswith("[job event]") and not self._raised:
            self._raised = True
            yield StreamEvent(
                uuid="u",
                session_id="sess-1",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "hello "},
                },
            )
            raise RuntimeError("stream broke")
        async for message in super().receive_response():
            yield message


@pytest.fixture(autouse=True)
def _reset():
    FakeClient.instances.clear()
    BlockingClient.instances.clear()


def _cfg(tmp_path) -> BrainConfig:
    return BrainConfig(
        cwd=tmp_path, state_dir=tmp_path / "state", journal_dir=tmp_path / "walk", repos=[]
    )


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
    # No model turn: the work is in the inbox and the spoken line is a template.
    assert not any(q.startswith("[job event]") for q in client.queries)
    assert ev.text == "morning is done. It's in your inbox."
    item = inbox.get(ev.job.inbox_id)
    assert item["source"] == "job" and item["summary_md"] == "Briefing done. Two meetings."
    # Not delivered until the transport has actually pushed it.
    assert brain.jobs.status(ev.job.id).delivered is False
    brain.ack(ev.job)
    assert brain.jobs.status(ev.job.id).delivered is True
    await brain.stop()


async def test_interrupt_drains_then_allows_send(tmp_path):
    """Interrupting a live send() only signals the client (the send() loop itself
    picks up the terminal ResultMessage); once that turn finishes, later sends work."""
    brain = Brain(_cfg(tmp_path), _yes, client_factory=BlockingClient, runner=None)
    await brain.start()

    gen = brain.send("hi")
    first = await gen.__anext__()
    assert first == "hello"

    client = BlockingClient.instances[0]
    await brain.interrupt()
    assert client.interrupted is True

    client.release.set()
    rest = "".join([chunk async for chunk in gen])
    assert (first + rest).strip() == "hello"

    text = await _collect(brain.send("again"))
    assert text.strip() == "hello"
    await brain.stop()


async def test_abandoned_send_does_not_strand_lock(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=BlockingClient, runner=None)
    await brain.start()

    gen = brain.send("one")
    first = await gen.__anext__()
    assert first == "hello"

    client = BlockingClient.instances[0]
    client.release.set()
    await gen.aclose()

    text = await asyncio.wait_for(_collect(brain.send("two")), 2)
    assert text.strip() == "hello"
    assert client.interrupted is True
    await brain.stop()


async def test_interrupt_when_idle_returns_immediately(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None)
    await brain.start()
    await asyncio.wait_for(brain.interrupt(), 1)
    client = FakeClient.instances[0]
    assert client.interrupted is False
    await brain.stop()


async def test_corrupt_session_file_starts_fresh(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "session.json").write_text("{not json")
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None)
    await brain.start()
    assert FakeClient.instances[0].options.resume is None
    await brain.stop()


async def test_events_survive_ask_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(concierge_module, "EVENT_RETRY_DELAY_S", 0.01)

    async def runner(rec):
        return 0, json.dumps({"is_error": False, "result": "Briefing done."}), ""

    brain = Brain(_cfg(tmp_path), _yes, client_factory=FlakyOnceClient, runner=runner)
    await brain.start()
    events = brain.events()
    await brain.jobs.dispatch("morning", "/morning")
    ev = await asyncio.wait_for(events.__anext__(), 2)
    assert isinstance(ev, SpokenEvent)
    brain.ack(ev.job)
    assert brain.jobs.status(ev.job.id).delivered is True
    await brain.stop()


async def test_concurrent_interrupt_during_abandoned_send_drains_once(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=BlockingClient, runner=None)
    await brain.start()

    gen = brain.send("one")
    first = await gen.__anext__()
    assert first == "hello"

    client = BlockingClient.instances[0]
    client.release.set()

    await asyncio.gather(gen.aclose(), brain.interrupt())

    assert client.interrupt_calls == 1
    assert client.receive_response_calls <= 2

    text = await asyncio.wait_for(_collect(brain.send("two")), 2)
    assert text.strip() == "hello"
    await brain.stop()


class ResumeRefusingClient(FakeClient):
    """Rejects any attempt to resume, as the CLI does for a session it no longer has."""

    async def connect(self):
        if self.options.resume is not None:
            raise RuntimeError("no conversation found with session id")
        await super().connect()


async def test_stale_resume_id_starts_a_fresh_session(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "session.json").write_text(json.dumps({"session_id": "gone", "date": "2026-09-08"}))

    brain = Brain(_cfg(tmp_path), _yes, client_factory=ResumeRefusingClient, runner=None)
    await brain.start()

    assert ResumeRefusingClient.instances[0].options.resume == "gone"
    assert ResumeRefusingClient.instances[1].options.resume is None
    assert brain.session_id is None
    text = await asyncio.wait_for(_collect(brain.send("hi")), 2)
    assert text.strip() == "hello there"
    await brain.stop()


async def test_send_and_job_event_are_journaled(tmp_path):
    async def runner(rec):
        return 0, json.dumps({"is_error": False, "result": "Briefing done."}), ""

    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=runner)
    await brain.start()
    await _collect(brain.send("what's on"))
    events = brain.events()
    await brain.jobs.dispatch("morning", "/morning")
    await asyncio.wait_for(events.__anext__(), 2)
    files = list((tmp_path / "walk").glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "**Mark:** what's on" in text
    assert "**Synthia:** hello there" in text
    assert "**Job done:** morning — Briefing done." in text
    await brain.stop()


async def test_desk_turn_is_tagged_and_origin_is_scoped_to_the_turn(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=None)
    await brain.start()
    seen = []
    async for _ in brain.send("what is going on", origin="desk"):
        seen.append(brain.turn_origin)
    assert set(seen) == {"desk"}
    assert FakeClient.instances[-1].queries[-1] == "[desk] what is going on"
    assert brain.turn_origin is None
    await _collect(brain.send("hello", origin="telegram"))
    assert FakeClient.instances[-1].queries[-1] == "hello"
    await brain.stop()


async def test_interrupt_only_stops_a_turn_from_the_same_transport(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=BlockingClient, runner=None)
    await brain.start()
    gen = brain.send("hi", origin="desk")
    assert await gen.__anext__() == "hello"
    client = BlockingClient.instances[0]
    await brain.interrupt("telegram")  # a Telegram /stop must not cut off a desk turn
    assert client.interrupted is False
    await brain.interrupt(None)
    assert client.interrupted is False
    await brain.interrupt("desk")
    assert client.interrupted is True
    client.release.set()
    [c async for c in gen]

    BlockingClient.instances.clear()
    brain2 = Brain(_cfg(tmp_path / "b"), _yes, client_factory=BlockingClient, runner=None)
    await brain2.start()
    gen = brain2.send("hi", origin="telegram")
    await gen.__anext__()
    c2 = BlockingClient.instances[0]
    await brain2.interrupt("desk")  # and the desk must not cut off a Telegram turn
    assert c2.interrupted is False
    await brain2.interrupt("telegram")
    assert c2.interrupted is True
    c2.release.set()
    [c async for c in gen]


async def test_requeued_job_event_is_not_asked_again(tmp_path):
    async def runner(rec):
        return 0, json.dumps({"is_error": False, "result": "Done."}), ""

    brain = Brain(_cfg(tmp_path), _yes, client_factory=FakeClient, runner=runner)
    await brain.start()
    events = brain.events()
    await brain.jobs.dispatch("morning", "/morning")
    ev = await asyncio.wait_for(events.__anext__(), 2)
    client = FakeClient.instances[-1]
    asked = len(client.queries)
    brain.requeue(ev.job)
    again = await asyncio.wait_for(events.__anext__(), 2)
    assert again.text == ev.text
    assert len(client.queries) == asked
    await brain.stop()


def _scripted(script, final=""):
    class Client(ScriptedClient):
        pass

    Client.script = script
    Client.final = final
    return Client


async def test_narration_before_a_tool_call_is_dropped(tmp_path):
    script = [
        *_text_message("Reading is fine. ", "Read the two panes.", tool=True),
        *_text_message("The admin pane is on the hotfix."),
    ]
    brain = Brain(_cfg(tmp_path), _yes, client_factory=_scripted(script, "x"), runner=None)
    await brain.start()
    chunks = [c async for c in brain.send("what's going on", origin="desk")]
    assert chunks == ["The admin pane is on the hotfix."]
    await brain.stop()


async def test_two_text_messages_are_joined_with_a_space(tmp_path):
    script = [*_text_message("First thing."), *_text_message("Second thing.")]
    brain = Brain(_cfg(tmp_path), _yes, client_factory=_scripted(script), runner=None)
    await brain.start()
    chunks = [c async for c in brain.send("hi")]
    assert "".join(chunks) == "First thing. Second thing."
    await brain.stop()


async def test_narration_never_reaches_telegram_or_the_journal(tmp_path):
    script = [
        *_text_message("Let me check.", tool=True),
        *_text_message("All quiet."),
    ]
    brain = Brain(_cfg(tmp_path), _yes, client_factory=_scripted(script), runner=None)
    await brain.start()
    # Telegram joins send() chunks exactly like this.
    reply = "".join([c async for c in brain.send("status", origin="telegram")]).strip()
    assert reply == "All quiet."
    assert "Let me check" not in next((tmp_path / "walk").glob("*.md")).read_text()
    await brain.stop()


async def test_result_text_is_the_fallback_when_nothing_streamed(tmp_path):
    brain = Brain(_cfg(tmp_path), _yes, client_factory=_scripted([], "Done."), runner=None)
    await brain.start()
    assert [c async for c in brain.send("hi")] == ["Done."]
    await brain.stop()
