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
        self.interrupts = 0
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

    async def send(self, text):
        self.sent.append(text)
        yield "reply to "
        yield text

    async def interrupt(self):
        self.interrupts += 1

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

    async def send_voice(self, chat_id, voice, caption=None, **kw):
        if self.fail_send_voice_times > 0:
            self.fail_send_voice_times -= 1
            raise RuntimeError("send_voice failed")
        self.voices.append((chat_id, caption))

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)

    async def send_message(self, chat_id, text, **kw):
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


async def test_pump_events_pushes_voice(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "Briefing is done, two meetings today."))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert bot.voices[-1] == (1, "Briefing is done, two meetings today.")
    assert brain.acked == [rec]
    assert rec.delivered is True


def test_build_app_enables_concurrent_updates(parts):
    brain, speech, bot, tr, ctx = parts
    app = tr.build_app("123:abc")
    assert app.concurrent_updates
    assert app.concurrent_updates > 1


async def test_pump_events_survives_send_failure(parts):
    brain, speech, bot, tr, ctx = parts
    from synthia.brain.concierge import SpokenEvent

    bot.fail_send_voice_times = 1
    rec = JobRecord(id="a", name="morning", prompt="/morning", started="t", status="done")
    pump = asyncio.create_task(tr.pump_events(bot))
    await brain._events.put(SpokenEvent(rec, "first event, send fails"))
    await asyncio.sleep(0.05)
    await brain._events.put(SpokenEvent(rec, "second event, delivered"))
    await asyncio.sleep(0.05)
    pump.cancel()
    assert bot.voices[-1] == (1, "second event, delivered")


async def test_on_error_notifies_chat(parts):
    brain, speech, bot, tr, ctx = parts
    fake_ctx = SimpleNamespace(bot=bot, error=RuntimeError("boom"))
    fake_update = SimpleNamespace(message=SimpleNamespace(text="hi"))
    await tr.on_error(fake_update, fake_ctx)
    assert any(t == "Something went wrong on my end. Try again?" for _, t in bot.texts)


async def test_on_error_polling_conflict_warns_once_per_hour(parts, monkeypatch):
    """A getUpdates Conflict (second bot on the token) has no update to answer.

    Regression: a duplicate poller made the brain post "Something went wrong"
    to the chat every ~35 s for hours. Now: one pointed notice, then silence
    for an hour.
    """
    from telegram.error import Conflict

    brain, speech, bot, tr, ctx = parts
    tr.chat_id = 1
    clock = [1000.0]
    monkeypatch.setattr(telegram_module.time, "monotonic", lambda: clock[0])
    fake_ctx = SimpleNamespace(bot=bot, error=Conflict("terminated by other getUpdates request"))
    for _ in range(5):
        await tr.on_error(None, fake_ctx)
        clock[0] += 35
    assert len(bot.texts) == 1
    assert "Another bot is polling my Telegram token" in bot.texts[0][1]
    assert "Something went wrong" not in bot.texts[0][1]
    clock[0] += 3600
    await tr.on_error(None, fake_ctx)
    assert len(bot.texts) == 2


async def test_on_error_polling_network_error_stays_quiet(parts):
    brain, speech, bot, tr, ctx = parts
    fake_ctx = SimpleNamespace(bot=bot, error=RuntimeError("network down"))
    await tr.on_error(None, fake_ctx)
    assert bot.texts == []


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
    assert bot.voices == []


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
    assert bot.voices[-1] == (1, "Briefing is done after the crash.")


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
