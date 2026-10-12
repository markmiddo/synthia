import threading
import time

from synthia.brain_client import BrainUnavailable
from synthia.desk_voice import UNREACHABLE_LINE, DeskVoice, SentenceBuffer


def _wait(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_sentence_buffer_splits_across_deltas():
    buf = SentenceBuffer()
    assert buf.push("Two agents are wor") == []
    assert buf.push("king. One needs you") == ["Two agents are working."]
    assert buf.push(" now. Want") == ["One needs you now."]
    assert buf.flush() == "Want"
    assert buf.flush() is None


def test_sentence_buffer_keeps_short_fragments_attached():
    buf = SentenceBuffer()
    assert buf.push("Yes. The gallery is merged. ") == ["Yes. The gallery is merged."]


def test_sentence_buffer_newline_is_a_boundary():
    buf = SentenceBuffer()
    assert buf.push("First line\nSecond") == ["First line"]
    assert buf.flush() == "Second"


class FakeClient:
    def __init__(self, on_frame, down=False):
        self.on_frame = on_frame
        self.down = down
        self.said, self.interrupts, self.confirms = [], 0, []

    def say(self, text):
        if self.down:
            raise BrainUnavailable("down")
        self.said.append(text)

    def interrupt(self):
        self.interrupts += 1

    def confirm_reply(self, cid, yes):
        self.confirms.append((cid, yes))

    def close(self):
        pass


def _voice(down=False, speak=None):
    spoken = []
    stops = []
    holder = {}

    def factory(on_frame):
        holder["client"] = FakeClient(on_frame, down)
        return holder["client"]

    v = DeskVoice(factory, speak or spoken.append, lambda: stops.append(1))
    return v, holder["client"], spoken, stops


def test_reply_is_spoken_sentence_by_sentence():
    v, client, spoken, _ = _voice()
    v.ask("what's going on")
    assert client.said == ["what's going on"]
    assert v.busy
    client.on_frame({"type": "delta", "text": "Two agents are working. "})
    assert _wait(lambda: spoken == ["Two agents are working."])  # spoken before the reply ends
    client.on_frame({"type": "delta", "text": "One needs you"})
    client.on_frame({"type": "reply_done", "text": ""})
    assert _wait(lambda: spoken == ["Two agents are working.", "One needs you"])
    assert _wait(lambda: not v.busy)
    v.close()


def test_events_are_spoken():
    v, client, spoken, _ = _voice()
    client.on_frame({"type": "event", "text": "The gallery job finished."})
    assert _wait(lambda: spoken == ["The gallery job finished."])
    v.close()


def test_brain_down_is_announced_once():
    v, client, spoken, _ = _voice(down=True)
    v.ask("hello")
    v.ask("hello again")
    assert _wait(lambda: spoken == [UNREACHABLE_LINE])
    time.sleep(0.1)
    assert spoken == [UNREACHABLE_LINE]
    client.down = False
    v.ask("back now")
    assert client.said == ["back now"]
    client.down = True
    v.ask("down again")
    assert _wait(lambda: spoken == [UNREACHABLE_LINE, UNREACHABLE_LINE])
    v.close()


def test_interrupt_stops_speech_drops_queue_and_discards_the_tail():
    gate = threading.Event()
    spoken = []

    def slow_speak(line):
        spoken.append(line)
        gate.wait(1)

    v, client, _, stops = _voice(speak=slow_speak)
    v.ask("tell me")
    client.on_frame({"type": "delta", "text": "First sentence here. Second sentence here. "})
    assert _wait(lambda: spoken == ["First sentence here."])
    v.interrupt()
    gate.set()
    assert stops == [1] and client.interrupts == 1
    # the tail of the interrupted reply arrives afterwards and must not be spoken
    client.on_frame({"type": "delta", "text": "Third sentence here. "})
    client.on_frame({"type": "reply_done", "text": ""})
    time.sleep(0.2)
    assert spoken == ["First sentence here."]
    # the next reply is spoken normally
    v.ask("again")
    client.on_frame({"type": "delta", "text": "Fresh reply to you. "})
    assert _wait(lambda: spoken[-1] == "Fresh reply to you.")
    v.close()


def test_confirm_is_spoken_and_next_utterance_answers_it():
    v, client, spoken, _ = _voice()
    client.on_frame({"type": "confirm", "id": "abc", "question": "merge the gallery PR"})
    assert _wait(lambda: spoken and "merge the gallery PR" in spoken[0])
    assert v.awaiting_confirmation
    v.ask("yes go ahead")
    assert client.confirms == [("abc", True)]
    assert client.said == []
    assert not v.awaiting_confirmation
    v.close()


def test_confirm_answer_no():
    v, client, spoken, _ = _voice()
    client.on_frame({"type": "confirm", "id": "x", "question": "do a thing"})
    v.ask("no, leave it")
    assert client.confirms == [("x", False)]
    v.close()
