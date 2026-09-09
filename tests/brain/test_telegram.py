import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from synthia.brain.jobs import JobRecord
from synthia.brain.transports.telegram import TelegramTransport, is_yes


class FakeBrain:
    def __init__(self):
        self.sent = []
        self.interrupts = 0
        self.new_sessions = 0
        self._events: asyncio.Queue = asyncio.Queue()
        self.jobs = SimpleNamespace(list_jobs=lambda: [])

    async def send(self, text):
        self.sent.append(text)
        yield "reply to "
        yield text

    async def interrupt(self):
        self.interrupts += 1

    async def new_session(self, handover=None):
        self.new_sessions += 1

    async def events(self):
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
    await tr.on_error(None, fake_ctx)
    assert any(t == "Something went wrong on my end. Try again?" for _, t in bot.texts)


async def test_speak_cleans_up_on_send_failure(parts):
    brain, speech, bot, tr, ctx = parts
    bot.fail_send_voice_times = 1
    ogg_path = tr.work_dir / "out" / "1.ogg"
    with pytest.raises(RuntimeError):
        await tr._speak(bot, 1, "hello")
    assert not ogg_path.exists()
