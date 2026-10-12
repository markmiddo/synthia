import asyncio
import json
import stat
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from synthia.brain.routing import Router
from synthia.brain.transports.desk import CLOSE_UNAUTHORISED, DeskTransport


class FakeBrain:
    def __init__(self):
        self.sent = []
        self.interrupts = 0
        self.interrupt_origins = []
        self.journal = SimpleNamespace(confirmation=lambda q, ok: self.confirmed.append((q, ok)))
        self.confirmed = []
        self.turn_origin = None
        self.fail = False
        self.gate = None  # optional asyncio.Event the reply waits on

    async def send(self, text, origin=None):
        self.sent.append((text, origin))
        if self.fail:
            raise RuntimeError("boom")
        yield "Two agents "
        if self.gate is not None:
            await self.gate.wait()
        yield "are working."

    async def interrupt(self, origin=None):
        self.interrupts += 1
        self.interrupt_origins.append(origin)


@pytest.fixture
async def desk(tmp_path):
    brain = FakeBrain()
    d = DeskTransport(brain, 0, tmp_path / "state" / "desk.token", confirm_timeout_s=1)
    await d.start()
    yield d
    await d.stop()


async def _client(desk):
    ws = await connect(f"ws://127.0.0.1:{desk.bound_port}")
    await ws.send(json.dumps({"type": "auth", "token": desk.token}))
    first = json.loads(await asyncio.wait_for(ws.recv(), 2))
    assert first == {"type": "state", "value": "idle"}
    return ws


async def _until(ws, kind):
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if frame["type"] == kind:
            return frame


async def test_token_file_is_private_and_removed_on_stop(tmp_path):
    d = DeskTransport(FakeBrain(), 0, tmp_path / "s" / "desk.token", confirm_timeout_s=1)
    await d.start()
    path = tmp_path / "s" / "desk.token"
    assert path.read_text() == d.token
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    await d.stop()
    assert not path.exists()


async def test_say_round_trip(desk):
    ws = await _client(desk)
    await ws.send(json.dumps({"type": "say", "text": "what's going on"}))
    states, deltas = [], []
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if frame["type"] == "state":
            states.append(frame["value"])
        elif frame["type"] == "delta":
            deltas.append(frame["text"])
        elif frame["type"] == "reply_done":
            done = frame
            break
    assert done["text"] == "Two agents are working."
    assert deltas == ["Two agents ", "are working."]
    assert states[:2] == ["thinking", "speaking"]
    assert (await _until(ws, "state"))["value"] == "idle"
    assert desk.brain.sent == [("what's going on", "desk")]
    await ws.close()


async def test_deltas_reach_every_client(desk):
    a, b = await _client(desk), await _client(desk)
    await a.send(json.dumps({"type": "say", "text": "hi"}))
    assert (await _until(b, "reply_done"))["text"] == "Two agents are working."
    await a.close()
    await b.close()


async def test_wrong_token_rejected(desk):
    ws = await connect(f"ws://127.0.0.1:{desk.bound_port}")
    await ws.send(json.dumps({"type": "auth", "token": "nope"}))
    with pytest.raises(ConnectionClosed) as exc:
        await asyncio.wait_for(ws.recv(), 2)
    assert exc.value.rcvd.code == CLOSE_UNAUTHORISED
    assert not desk.has_clients


async def test_say_before_auth_rejected(desk):
    ws = await connect(f"ws://127.0.0.1:{desk.bound_port}")
    await ws.send(json.dumps({"type": "say", "text": "hi"}))
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(ws.recv(), 2)
    assert desk.brain.sent == []


async def test_interrupt_reaches_brain(desk):
    ws = await _client(desk)
    await ws.send(json.dumps({"type": "interrupt"}))
    for _ in range(50):
        if desk.brain.interrupts:
            break
        await asyncio.sleep(0.02)
    assert desk.brain.interrupts == 1
    await ws.close()


async def test_turn_failure_is_reported_not_swallowed(desk):
    desk.brain.fail = True
    ws = await _client(desk)
    await ws.send(json.dumps({"type": "say", "text": "hi"}))
    assert "boom" in (await _until(ws, "error"))["text"]
    assert (await _until(ws, "reply_done"))["text"] == ""
    await ws.close()


async def test_event_push(desk):
    ws = await _client(desk)
    await desk.push_event("The gallery job finished.")
    assert (await _until(ws, "event"))["text"] == "The gallery job finished."
    await ws.close()


async def test_confirm_round_trip(desk):
    ws = await _client(desk)
    task = asyncio.create_task(desk.confirm("merge the PR"))
    frame = await _until(ws, "confirm")
    assert frame["question"] == "merge the PR"
    await ws.send(json.dumps({"type": "confirm_reply", "id": frame["id"], "yes": True}))
    assert await asyncio.wait_for(task, 2) is True
    assert desk.brain.confirmed == [("merge the PR", True)]
    await ws.close()


async def test_confirm_times_out_as_no(desk):
    ws = await _client(desk)
    assert await desk.confirm("merge the PR") is False
    await ws.close()


async def test_confirm_without_client_denies(desk):
    assert await desk.confirm("merge the PR") is False


# ---- routing ----


class FakeTransport:
    def __init__(self, name, connected=True, answer=True, delay=0.0):
        self.name = name
        self.has_clients = connected
        self.asked = []
        self.answer = answer
        self.delay = delay
        self.cancelled = False
        self.pushed = []

    async def ask(self, question):
        self.asked.append(question)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.answer

    async def push_event(self, text):
        self.pushed.append(text)


def _router(origin, desk_connected=True, with_telegram=True, **kw):
    desk = FakeTransport("desk", desk_connected, **kw.get("desk", {}))
    tg = FakeTransport("telegram", **kw.get("tg", {})) if with_telegram else None
    r = Router(desk, tg)
    r.brain = SimpleNamespace(turn_origin=origin)
    return r, desk, tg


async def test_confirm_goes_to_originating_transport():
    r, desk, tg = _router("telegram")
    assert await r.confirm("q")
    assert tg.asked == ["q"] and desk.asked == []
    r, desk, tg = _router("desk")
    assert await r.confirm("q")
    assert desk.asked == ["q"] and tg.asked == []


async def test_job_event_confirm_asks_both_and_first_answer_wins():
    r, desk, tg = _router(None, desk=dict(answer=True), tg=dict(answer=False, delay=5))
    assert await r.confirm("q") is True
    assert desk.asked == ["q"] and tg.asked == ["q"]
    assert tg.cancelled
    r, desk, tg = _router(None, desk=dict(answer=True, delay=5), tg=dict(answer=False))
    assert await r.confirm("q") is False
    assert desk.cancelled


async def test_a_leg_with_nobody_to_answer_does_not_win():
    r, desk, tg = _router(None, desk=dict(answer=None), tg=dict(answer=True, delay=0.05))
    assert await r.confirm("q") is True


async def test_job_event_confirm_with_desk_gone_goes_to_telegram_only():
    r, desk, tg = _router(None, desk_connected=False)
    await r.confirm("q")
    assert tg.asked == ["q"] and desk.asked == []


async def test_desk_turn_falls_back_to_telegram_when_client_gone():
    r, desk, tg = _router("desk", desk_connected=False)
    await r.confirm("q")
    assert tg.asked == ["q"]


async def test_no_transport_denies():
    r, desk, _ = _router("desk", desk_connected=False, with_telegram=False)
    assert await r.confirm("q") is False


async def test_mirror_event_copies_to_desk_once_and_never_raises():
    r, desk, _ = _router(None)
    ev = SimpleNamespace(job=SimpleNamespace(id="a", name="n"), text="Done.")
    await r.mirror_event(ev)
    await r.mirror_event(ev)
    assert desk.pushed == ["Done."]
    desk.has_clients = False
    await r.mirror_event(SimpleNamespace(job=SimpleNamespace(id="b", name="n"), text="x"))
    assert desk.pushed == ["Done."]

    async def boom(text):
        raise RuntimeError("socket")

    desk.has_clients = True
    desk.push_event = boom
    await r.mirror_event(SimpleNamespace(job=SimpleNamespace(id="c", name="n"), text="x"))


async def test_confirm_done_follows_every_confirm(desk):
    ws = await _client(desk)
    task = asyncio.create_task(desk.confirm("merge the PR"))
    frame = await _until(ws, "confirm")
    await ws.send(json.dumps({"type": "confirm_reply", "id": frame["id"], "yes": True}))
    done = await _until(ws, "confirm_done")
    assert done == {"type": "confirm_done", "id": frame["id"], "approved": True}
    assert await task is True
    # a timeout closes the card with null, not false
    frame = None
    task = asyncio.create_task(desk.confirm("again"))
    frame = await _until(ws, "confirm")
    done = await _until(ws, "confirm_done")
    assert done["id"] == frame["id"] and done["approved"] is None
    assert await task is False
    await ws.close()


async def test_cancelled_confirm_closes_the_card(desk):
    ws = await _client(desk)
    task = asyncio.create_task(desk.ask("merge the PR"))
    frame = await _until(ws, "confirm")
    task.cancel()
    done = await _until(ws, "confirm_done")
    assert done["id"] == frame["id"] and done["approved"] is None
    await ws.close()


async def test_last_client_dropping_releases_a_pending_confirm(tmp_path):
    brain = FakeBrain()
    d = DeskTransport(brain, 0, tmp_path / "desk.token", confirm_timeout_s=60)
    await d.start()
    try:
        ws = await _client(d)
        task = asyncio.create_task(d.ask("merge the PR"))
        await _until(ws, "confirm")
        await ws.close()
        assert await asyncio.wait_for(task, 3) is None
    finally:
        await d.stop()


async def test_interrupt_frame_is_scoped_to_desk_turns(desk):
    ws = await _client(desk)
    await ws.send(json.dumps({"type": "interrupt"}))
    for _ in range(50):
        if desk.brain.interrupts:
            break
        await asyncio.sleep(0.02)
    assert desk.brain.interrupt_origins == ["desk"]
    await ws.close()
