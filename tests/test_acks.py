import logging
import threading
import time
from pathlib import Path

from synthia.acks import ACK_LINES, AckBank
from synthia.brain_client import BrainUnavailable
from synthia.desk_voice import DeskVoice


def _wait(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakeClient:
    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.said, self.interrupts, self.confirms = [], 0, []

    def say(self, text):
        self.said.append(text)

    def interrupt(self):
        self.interrupts += 1

    def confirm_reply(self, cid, yes):
        self.confirms.append((cid, yes))

    def close(self):
        pass


def _voice(delay=0.05, speak=None, play_ack=None, ack="/acks/one.mp3"):
    events = []
    holder = {}

    def factory(on_frame):
        holder["client"] = FakeClient(on_frame)
        return holder["client"]

    def default_speak(line):
        events.append(("say", line))

    def default_ack(path):
        events.append(("ack", path))

    v = DeskVoice(
        factory,
        speak or default_speak,
        lambda: events.append(("stop", None)),
        ack_source=lambda: ack,
        play_ack=play_ack or default_ack,
        ack_delay_s=delay,
    )
    return v, holder["client"], events


def test_ack_plays_when_no_delta_arrives_in_time():
    v, client, events = _voice()
    v.ask("look into the visa thing")
    assert _wait(lambda: ("ack", "/acks/one.mp3") in events)
    v.close()


def test_ack_skipped_when_the_first_delta_is_fast():
    v, client, events = _voice(delay=0.3)
    v.ask("what's going on")
    client.on_frame({"type": "delta", "text": "Two agents are working. "})
    assert _wait(lambda: ("say", "Two agents are working.") in events)
    time.sleep(0.45)
    assert all(kind != "ack" for kind, _ in events)
    v.close()


def test_no_ack_for_a_confirm_reply():
    v, client, events = _voice()
    client.on_frame({"type": "confirm", "id": "c1", "question": "restart the thing"})
    assert _wait(lambda: any(k == "say" for k, _ in events))
    v.ask("yes")
    time.sleep(0.2)
    assert client.confirms == [("c1", True)]
    assert all(kind != "ack" for kind, _ in events)
    v.close()


def test_no_ack_when_the_brain_is_unreachable():
    holder = {}
    events = []

    class Down(FakeClient):
        def say(self, text):
            raise BrainUnavailable("down")

    def factory(on_frame):
        holder["c"] = Down(on_frame)
        return holder["c"]

    v = DeskVoice(
        factory,
        lambda line: events.append(("say", line)),
        lambda: None,
        ack_source=lambda: "/acks/one.mp3",
        play_ack=lambda p: events.append(("ack", p)),
        ack_delay_s=0.05,
    )
    v.ask("hello")
    time.sleep(0.2)
    assert all(kind != "ack" for kind, _ in events)
    v.close()


def test_ack_then_reply_in_order_and_never_overlapping():
    playing = []
    overlaps = []
    log = []
    gate = threading.Event()

    def begin(name):
        if playing:
            overlaps.append(name)
        playing.append(name)

    def end(name):
        playing.remove(name)

    def play_ack(path):
        begin("ack")
        log.append("ack")
        gate.wait(1)  # the ack is still playing when the reply's first sentence is ready
        end("ack")

    def speak(line):
        begin("reply")
        log.append(line)
        end("reply")

    v, client, _ = _voice(speak=speak, play_ack=play_ack)
    v.ask("look into that")
    assert _wait(lambda: log == ["ack"])
    client.on_frame({"type": "delta", "text": "Here is what I found. "})
    time.sleep(0.1)
    assert log == ["ack"]  # the reply waits for the ack to finish
    gate.set()
    assert _wait(lambda: log == ["ack", "Here is what I found."])
    assert overlaps == []
    v.close()


def test_interrupt_cancels_both_ack_and_reply():
    gate = threading.Event()
    played = []

    def play_ack(path):
        played.append("ack")
        gate.wait(1)

    v, client, events = _voice(play_ack=play_ack)
    v.ask("look into that")
    assert _wait(lambda: played == ["ack"])
    client.on_frame({"type": "delta", "text": "First sentence here. Second sentence here. "})
    v.interrupt()
    gate.set()
    time.sleep(0.2)
    assert ("stop", None) in events
    assert [e for e in events if e[0] == "say"] == []  # queued reply sentences were dropped
    assert client.interrupts == 1
    v.close()


def test_interrupt_before_the_timer_means_no_ack():
    v, client, events = _voice(delay=0.2)
    v.ask("look into that")
    v.interrupt()
    time.sleep(0.4)
    assert all(kind != "ack" for kind, _ in events)
    v.close()


def test_turn_latency_is_logged_once(caplog):
    v, client, events = _voice(delay=5)
    caplog.set_level(logging.INFO, logger="synthia.desk_voice")
    v.ask("what's up", released_at=time.monotonic() - 1.7)
    client.on_frame({"type": "delta", "text": "All quiet at the moment. "})
    assert _wait(lambda: ("say", "All quiet at the moment.") in events)
    v.mark_audio_start()
    v.mark_audio_start()
    lines = [r.message for r in caplog.records if r.message.startswith("desk turn:")]
    assert len(lines) == 1
    assert "release to transcript" in lines[0] and "first delta to first audio" in lines[0]
    v.close()


def test_ack_bank_renders_once_per_voice_and_rotates(tmp_path: Path):
    rendered = []

    def render(text, path):
        rendered.append(text)
        Path(path).write_bytes(b"mp3")
        return True

    bank = AckBank("en-US-Chirp3-HD-Leda", render, cache_root=tmp_path)
    assert bank.next() is None  # nothing ready yet
    assert bank.prepare() == len(ACK_LINES)
    assert bank.prepare() == 0  # cached
    seen = {bank.next() for _ in ACK_LINES}
    assert len(seen) == len(ACK_LINES)
    assert all(str(tmp_path / "en-US-Chirp3-HD-Leda") in p for p in seen)

    other = AckBank("en-GB-Neural2-A", render, cache_root=tmp_path)
    assert other.prepare() == len(ACK_LINES)  # a new voice is regenerated in its own folder
    assert len(rendered) == 2 * len(ACK_LINES)
