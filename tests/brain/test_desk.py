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
        self.inboxed = []
        self.present = True
        self.resolution = "unset"

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

    async def push_inbox(self, item_id, title):
        self.inboxed.append((item_id, title))

    @property
    def is_present(self):
        return self.present

    def resolved(self, approved):
        self.resolution = approved


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


def _ev(name="growth squad", jid="squad-1", ok=True, summary="Two blog drafts are ready."):
    from synthia import inbox
    from synthia.brain.jobs import JobRecord

    rec = JobRecord(id=jid, name=name, prompt="", started="t", ok=ok, summary=summary)
    rec.inbox_id = inbox.create_from_job(rec)["id"]
    return SimpleNamespace(job=rec, text="Growth's posts are ready in your inbox.")


async def _away(sent):
    async def send(text):
        sent.append(text)

    return send


async def test_desk_mode_pushes_inbox_frame_and_spoken_line_and_skips_telegram():
    from synthia import inbox

    r, desk, tg = _router(None)  # connected and present
    ev = _ev()
    sent = []
    assert await r.deliver_event(ev, await _away(sent)) is True
    assert desk.inboxed == [(ev.job.inbox_id, ev.job.name)]
    assert desk.pushed == [ev.text]
    assert sent == []
    assert inbox.get(ev.job.inbox_id)["notified"] == {
        "desk": True,
        "telegram": False,
        "email": False,
    }


async def test_away_mode_sends_one_short_text_and_leaves_the_desk_alone():
    from synthia import inbox

    r, desk, tg = _router(None)
    desk.present = False
    ev = _ev()
    sent = []
    assert await r.deliver_event(ev, await _away(sent)) is True
    assert len(sent) == 1 and len(sent[0]) < 300
    assert "Say 'email it'" in sent[0] and "Two blog drafts are ready." in sent[0]
    assert desk.pushed == [] and desk.inboxed == []
    assert inbox.get(ev.job.inbox_id)["notified"]["telegram"] is True
    # A requeue after a lost ack does not text a second time.
    assert await r.deliver_event(ev, await _away(sent)) is True
    assert len(sent) == 1


async def test_away_mode_with_no_client_connected():
    r, desk, tg = _router(None, desk_connected=False)
    sent = []
    assert await r.deliver_event(_ev(), await _away(sent)) is True
    assert len(sent) == 1


async def test_away_send_failure_propagates_so_the_caller_retries():
    from synthia import inbox

    r, desk, tg = _router(None, desk_connected=False)
    ev = _ev()

    async def boom(text):
        raise RuntimeError("telegram down")

    with pytest.raises(RuntimeError):
        await r.deliver_event(ev, boom)
    assert inbox.get(ev.job.inbox_id)["notified"]["telegram"] is False


async def test_desk_only_with_idle_client_still_delivers_to_the_desk():
    r, desk, _ = _router(None, with_telegram=False)
    desk.present = False
    assert await r.deliver_event(_ev()) is True
    assert len(desk.pushed) == 1


async def test_nobody_to_tell_means_not_delivered():
    r, desk, _ = _router(None, desk_connected=False, with_telegram=False)
    assert await r.deliver_event(_ev()) is False


async def test_desk_push_failure_means_not_delivered_then_retry_delivers_once():
    r, desk, _ = _router(None, with_telegram=False)
    ev = _ev()

    async def boom(text):
        raise RuntimeError("socket")

    real, desk.push_event = desk.push_event, boom
    assert await r.deliver_event(ev) is False
    desk.push_event = real
    assert await r.deliver_event(ev) is True
    assert await r.deliver_event(ev) is True  # already told: stays delivered across requeues
    assert desk.pushed == [ev.text]


async def test_losing_leg_is_told_the_winning_answer():
    r, desk, tg = _router(None, desk={"delay": 0.2}, tg={"answer": False})
    assert await r.confirm("q") is False
    assert desk.cancelled and desk.resolution is False
    assert tg.resolution == "unset"  # the winner is not told


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


async def test_desk_card_closes_with_the_real_answer_when_telegram_won(desk):
    ws = await _client(desk)
    task = asyncio.create_task(desk.ask("merge the PR"))
    await _until(ws, "confirm")
    desk.resolved(True)  # the Router: the phone approved first
    task.cancel()
    done = await _until(ws, "confirm_done")
    assert done["approved"] is True
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_desk_only_pump_acks_only_when_the_desk_has_the_event(monkeypatch):
    from synthia.brain import serve

    monkeypatch.setattr("synthia.brain.concierge.EVENT_RETRY_DELAY_S", 0.01)
    r, desk, _ = _router(None, with_telegram=False)
    ev = SimpleNamespace(job=SimpleNamespace(id="a", name="n", inbox_id="", ok=True), text="Done.")
    calls = {"acked": [], "requeued": []}

    class B:
        async def events(self):
            yield ev
            await asyncio.sleep(3600)

        def ack(self, job):
            calls["acked"].append(job)

        def requeue(self, job):
            calls["requeued"].append(job)

    async def boom(text):
        raise RuntimeError("socket")

    desk.push_event = boom
    ev.job.inbox_id = ""
    pump = asyncio.create_task(serve._pump_desk_events(B(), r))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert calls["acked"] == [] and calls["requeued"] == [ev.job]


# ---- presence ----


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
async def clocked(tmp_path):
    clock = Clock()
    d = DeskTransport(FakeBrain(), 0, tmp_path / "desk.token", confirm_timeout_s=1, clock=clock)
    await d.start()
    yield d, clock
    await d.stop()


async def _presence(ws, desk, active):
    await ws.send(json.dumps({"type": "presence", "active": active}))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if (desk._presence_at is not None) == active:
            return


async def test_not_present_without_a_client_or_a_signal(clocked):
    desk, clock = clocked
    assert desk.is_present is False
    ws = await _client(desk)
    assert desk.is_present is False  # connected, but nothing says Mark is here
    await ws.close()


async def test_presence_frame_counts_for_ten_minutes_then_lapses(clocked):
    desk, clock = clocked
    ws = await _client(desk)
    await _presence(ws, desk, True)
    assert desk.is_present is True
    clock.now += 9 * 60
    assert desk.is_present is True
    clock.now += 2 * 60
    assert desk.is_present is False
    await ws.close()


async def test_presence_inactive_withdraws_the_claim(clocked):
    desk, clock = clocked
    ws = await _client(desk)
    await _presence(ws, desk, True)
    await _presence(ws, desk, False)
    assert desk.is_present is False
    await ws.close()


async def test_recent_desk_voice_turn_counts_for_thirty_minutes(clocked):
    desk, clock = clocked
    ws = await _client(desk)
    await ws.send(json.dumps({"type": "say", "text": "hello"}))
    await _until(ws, "reply_done")
    clock.now += 29 * 60
    assert desk.is_present is True
    clock.now += 2 * 60
    assert desk.is_present is False
    await ws.close()


async def test_present_requires_a_connected_client(clocked):
    desk, clock = clocked
    ws = await _client(desk)
    await _presence(ws, desk, True)
    await ws.close()
    for _ in range(50):
        await asyncio.sleep(0.01)
        if not desk.has_clients:
            break
    assert desk.is_present is False


async def test_push_inbox_frame_shape(clocked):
    desk, clock = clocked
    ws = await _client(desk)
    await desk.push_inbox("abc", "Growth: week of posts")
    frame = await _until(ws, "inbox")
    assert frame == {"type": "inbox", "id": "abc", "title": "Growth: week of posts"}
    await ws.close()
