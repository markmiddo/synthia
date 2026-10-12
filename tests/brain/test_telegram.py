import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from synthia.brain.jobs import JobRecord
from synthia.brain.transports import telegram as telegram_module
from synthia.brain.transports.telegram import TelegramTransport, is_yes


class FakeBrain:
    def __init__(self):
        self.sent = []
        self.origins = []
        self.interrupts = 0
        self.interrupt_origins = []
        self.new_sessions = 0
        self._events: asyncio.Queue = asyncio.Queue()
        self.jobs = SimpleNamespace(list_jobs=lambda: [])
        self.acked: list = []
        self.requeued: list = []
        # Raise this many times from events() before yielding normally (test hook).
        self.fail_events_times = 0

    def ack(self, rec):
        rec.delivered = True
        self.acked.append(rec)

    def requeue(self, rec):
        self.requeued.append(rec)

    async def send(self, text, origin=None):
        self.sent.append(text)
        self.origins.append(origin)
        yield "reply to "
        yield text

    async def interrupt(self, origin=None):
        self.interrupts += 1
        self.interrupt_origins.append(origin)

    async def new_session(self, handover=None):
        self.new_sessions += 1

    async def events(self):
        if self.fail_events_times > 0:
            self.fail_events_times -= 1
            raise RuntimeError("events() blew up")
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
        # Raise this many times from send_voice before succeeding (test hook).
        self.fail_send_voice_times = 0
        self.fail_send_text_times = 0

    async def send_voice(self, chat_id, voice, caption=None, **kw):
        if self.fail_send_voice_times > 0:
            self.fail_send_voice_times -= 1
            raise RuntimeError("send_voice failed")
        self.voices.append((chat_id, caption))

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)

    async def send_message(self, chat_id, text, **kw):
        if self.fail_send_text_times > 0:
            self.fail_send_text_times -= 1
            raise RuntimeError("send_message failed")
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
    tr = TelegramTransport(
        brain, speech, allowed_users=[1], chat_id=1, confirm_timeout_s=1, work_dir=tmp_path
    )
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
    assert brain.origins == ["telegram"]
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
    assert brain.interrupt_origins == ["telegram"]
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


async def test_pump_events_sends_one_short_text_not_a_voice_note(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done, two meetings today."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert bot.texts[-1] == (1, "Briefing is done, two meetings today.")
    assert bot.voices == [] and speech.spoken == []
    assert brain.acked == [rec]
    assert rec.delivered is True


def test_build_app_enables_concurrent_updates(parts):
    brain, speech, bot, tr, ctx = parts
    app = tr.build_app("123:abc")
    assert app.concurrent_updates
    assert app.concurrent_updates > 1


async def test_pump_events_survives_send_failure(parts, monkeypatch):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    monkeypatch.setattr(telegram_module, "EVENT_RETRY_DELAY_S", 0.01)

    bot.fail_send_text_times = 1
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "first event, send fails"))
    await asyncio.sleep(0.05)
    await brain._events.put(SpokenEvent(rec, "second event, delivered"))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert bot.texts[-1] == (1, "second event, delivered")


async def test_on_error_notifies_chat(parts):
    brain, speech, bot, tr, ctx = parts
    fake_ctx = SimpleNamespace(bot=bot, error=RuntimeError("boom"))
    await tr.on_error(None, fake_ctx)
    assert any(t == "Something went wrong on my end. Try again?" for _, t in bot.texts)


async def test_speak_cleans_up_on_send_failure(parts):
    brain, speech, bot, tr, ctx = parts
    bot.fail_send_voice_times = 1
    ogg_path = tr.work_dir / "out" / "1.ogg"
    with pytest.raises(RuntimeError):
        await tr._speak(bot, 1, "hello")
    assert not ogg_path.exists()


async def test_pump_events_requeues_when_no_chat(parts, monkeypatch):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    monkeypatch.setattr(telegram_module, "EVENT_RETRY_DELAY_S", 0.01)
    tr.chat_id = None
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert brain.requeued == [rec]
    assert brain.acked == []
    assert rec.delivered is False
    assert bot.texts == []


async def test_pump_events_restarts_when_events_raises(parts, monkeypatch):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    monkeypatch.setattr(telegram_module, "EVENT_RETRY_DELAY_S", 0.01)
    brain.fail_events_times = 1
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await asyncio.sleep(0.05)
    await brain._events.put(SpokenEvent(rec, "Briefing is done after the crash."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert bot.texts[-1] == (1, "Briefing is done after the crash.")


async def test_confirm_denies_a_second_request_while_one_is_pending(parts):
    brain, speech, bot, tr, ctx = parts
    tr.bot = bot
    first = asyncio.create_task(tr.confirm("run git push origin main"))
    await asyncio.sleep(0.01)
    pending = tr._pending_confirm

    assert await tr.confirm("run gh pr merge 1") is False
    assert tr._pending_confirm is pending  # the first waiter was not stranded

    await tr.on_text(_update(text="yes", bot=bot), ctx)
    assert await first is True


async def test_non_yes_answer_is_taken_as_no(parts):
    brain, speech, bot, tr, ctx = parts
    tr.bot = bot
    task = asyncio.create_task(tr.confirm("run git push origin main"))
    await asyncio.sleep(0.01)
    await tr.on_text(_update(text="no, leave it", bot=bot), ctx)
    assert await task is False
    assert any(t == "Taken as no." for _, t in bot.texts)
    assert brain.sent == []


async def test_confirmation_is_journaled(parts, tmp_path):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.journal import WalkJournal

    brain.journal = WalkJournal(tmp_path / "walk")
    tr.bot = bot
    task = asyncio.create_task(tr.confirm("run git push origin main"))
    await asyncio.sleep(0.01)
    await tr.on_text(_update(text="no", bot=bot), ctx)
    assert await task is False
    text = brain.journal.today_path().read_text()
    assert "**Confirmation denied:** run git push origin main" in text


async def test_pump_events_hand_each_event_to_the_router_and_ack_on_true(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    routed = []

    async def deliver(ev, away):
        routed.append((ev.text, away is not None))
        return True

    tr.deliver_event = deliver
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert routed == [("Briefing is done.", True)]
    assert brain.acked == [rec]
    assert bot.texts == []  # the router chose the desk, so nothing went to Telegram


async def test_pump_events_with_no_chat_gives_the_router_no_away_channel(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    routed = []

    async def deliver(ev, away):
        routed.append(away)
        return False

    tr.deliver_event = deliver
    tr.chat_id = None
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert routed == [None]
    assert brain.requeued == [rec]
    assert brain.acked == []


async def test_pump_events_requeues_on_push_failure_without_acking(parts, monkeypatch):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    monkeypatch.setattr(telegram_module, "EVENT_RETRY_DELAY_S", 0.01)
    bot.fail_send_text_times = 1
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert brain.requeued == [rec]
    assert brain.acked == []


async def test_pump_events_gives_up_after_max_push_attempts(parts, monkeypatch):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    monkeypatch.setattr(telegram_module, "EVENT_RETRY_DELAY_S", 0.001)
    bot.fail_send_text_times = 100
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    for _ in range(telegram_module.MAX_EVENT_PUSH_ATTEMPTS):
        await brain._events.put(SpokenEvent(rec, "Briefing is done."))
    await asyncio.sleep(0.1)
    pump.cancel()
    assert len(brain.requeued) == telegram_module.MAX_EVENT_PUSH_ATTEMPTS - 1
    assert brain.acked == [rec]


async def test_losing_telegram_leg_says_where_it_was_answered(parts):
    brain, speech, bot, tr, ctx = parts
    tr.bot = bot
    task = asyncio.create_task(tr.ask("run git push"))
    await asyncio.sleep(0.01)
    tr.resolved(False)  # the Router: the desk declined first
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bot.texts[-1] == (1, "Answered at the desk: declined.")
    # And a late "yes" is no longer taken as an answer to a live question.
    assert tr._pending_confirm is None


async def test_cancelled_telegram_leg_without_winner_says_cancelled(parts):
    brain, speech, bot, tr, ctx = parts
    tr.bot = bot
    task = asyncio.create_task(tr.ask("run git push"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "cancelled" in bot.texts[-1][1]


async def test_text_timeout_counts_as_delivered_and_is_not_resent(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    timeouts = {"n": 0}

    async def slow_send_message(chat_id, text, **kw):
        timeouts["n"] += 1
        raise telegram_module.TimedOut("Timed out")

    bot.send_message = slow_send_message
    rec = JobRecord(id="a", name="office squad", prompt="", started="t", status="review")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Office sweep is ready."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert timeouts["n"] == 1, "a timed-out send must not be retried (Mark got three copies)"
    assert brain.acked == [rec]
