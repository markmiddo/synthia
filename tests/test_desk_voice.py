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


# ---- review fixes ----


def _press(voice):
    """Drive Synthia._on_assistant_press with just the parts it touches."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from synthia.main import Synthia

    fake = SimpleNamespace(
        running=True,
        assistant_active=False,
        dictation_active=False,
        desk_voice=voice,
        recorder=MagicMock(),
        sounds=MagicMock(),
        tray=None,
        _update_state=lambda status: None,
    )
    Synthia._on_assistant_press(fake)


def test_pressing_the_key_during_a_confirm_does_not_interrupt_the_turn():
    v, client, spoken, stops = _voice()
    v.ask("push it")
    client.on_frame({"type": "confirm", "id": "abc", "question": "push to main"})
    assert _wait(lambda: spoken and "push to main" in spoken[0])
    _press(v)
    assert client.interrupts == 0
    assert stops == [1]  # only the spoken question was cut off
    v.ask("yes")
    assert client.confirms == [("abc", True)]
    # the brain carries on with the same turn and the reply is spoken, not discarded
    client.on_frame({"type": "delta", "text": "Pushed it to main. "})
    client.on_frame({"type": "reply_done", "text": ""})
    assert _wait(lambda: spoken[-1] == "Pushed it to main.")
    v.close()


def test_pressing_the_key_mid_reply_still_interrupts():
    v, client, spoken, stops = _voice()
    v.ask("tell me")
    _press(v)
    assert client.interrupts == 1
    v.close()


def test_confirm_done_clears_a_stale_confirm_so_the_next_question_is_a_question():
    v, client, spoken, _ = _voice()
    client.on_frame({"type": "confirm", "id": "abc", "question": "merge it"})
    assert v.awaiting_confirmation
    client.on_frame({"type": "confirm_done", "id": "other", "approved": None})
    assert v.awaiting_confirmation  # a different question's close does not count
    client.on_frame({"type": "confirm_done", "id": "abc", "approved": None})
    assert not v.awaiting_confirmation
    v.ask("what's the weather")
    assert client.said == ["what's the weather"] and client.confirms == []
    v.close()


def test_disconnect_mid_reply_is_announced_once_and_clears_the_turn():
    v, client, spoken, _ = _voice()
    v.ask("tell me")
    client.on_frame({"type": "delta", "text": "Half a sente"})
    client.on_frame({"type": "disconnected"})
    assert _wait(lambda: spoken == [UNREACHABLE_LINE])
    client.on_frame({"type": "disconnected"})
    time.sleep(0.1)
    assert spoken == [UNREACHABLE_LINE]
    assert not v.busy
    v.ask("again")
    client.on_frame({"type": "delta", "text": "Fresh whole reply. "})
    client.on_frame({"type": "reply_done", "text": ""})
    assert _wait(lambda: spoken[-1] == "Fresh whole reply.")
    v.close()


def test_state_goes_thinking_speaking_ready():
    states = []
    holder = {}

    def factory(on_frame):
        holder["c"] = FakeClient(on_frame)
        return holder["c"]

    v = DeskVoice(factory, lambda line: None, lambda: None, on_state=states.append)
    client = holder["c"]
    v.ask("hi")
    assert states == ["thinking"]
    client.on_frame({"type": "delta", "text": "A whole sentence. "})
    assert _wait(lambda: "speaking" in states)
    assert states[-1] != "ready"  # the turn is still open
    client.on_frame({"type": "reply_done", "text": ""})
    assert _wait(lambda: states[-1] == "ready")
    assert states[0] == "thinking"
    v.close()


def test_state_is_ready_at_reply_done_when_the_last_sentence_already_finished():
    states = []
    holder = {}

    def factory(on_frame):
        holder["c"] = FakeClient(on_frame)
        return holder["c"]

    v = DeskVoice(factory, lambda line: None, lambda: None, on_state=states.append)
    client = holder["c"]
    v.ask("hi")
    client.on_frame({"type": "delta", "text": "A whole sentence. "})
    assert _wait(lambda: not v._outstanding)
    client.on_frame({"type": "reply_done", "text": ""})
    assert states[-1] == "ready"
    v.close()


def _voice_states(down=False, speak=None):
    states = []
    holder = {}

    def factory(on_frame):
        holder["client"] = FakeClient(on_frame, down)
        return holder["client"]

    spoken = []
    v = DeskVoice(factory, speak or spoken.append, lambda: None, on_state=states.append)
    return v, holder["client"], spoken, states


def test_late_speaker_and_reply_done_do_not_overwrite_recording():
    gate = threading.Event()
    started = threading.Event()

    def slow_speak(line):  # a real thread blocked in TTS, like the live speaker
        started.set()
        gate.wait(2)

    v, client, _, states = _voice_states(speak=slow_speak)
    v.ask("tell me a story")
    client.on_frame({"type": "delta", "text": "Once upon a long time ago. "})
    assert started.wait(2)
    v.begin_utterance()  # Right Alt goes down mid-sentence
    states.append("recording")  # what main.py writes next
    gate.set()  # the speaker returns after tts.cancel
    client.on_frame({"type": "reply_done", "text": ""})  # the brain's tail of the old reply
    time.sleep(0.2)
    assert states[-1] == "recording"
    assert "ready" not in states[states.index("recording") :]
    # Once the question is sent, state reporting resumes.
    v.ask("never mind")
    assert states[-1] == "thinking"
    client.on_frame({"type": "reply_done", "text": ""})
    assert _wait(lambda: states[-1] == "ready")


def test_abandoned_utterance_restores_ready():
    v, _, _, states = _voice_states()
    v.begin_utterance()
    states.append("recording")
    v.end_utterance()
    assert states[-1] == "ready"


def test_unreachable_every_press_ends_ready_and_speaks_sparingly(monkeypatch):
    import synthia.desk_voice as dv

    clock = [1000.0]
    monkeypatch.setattr(dv.time, "monotonic", lambda: clock[0])
    v, client, spoken, states = _voice_states(down=True)
    v.ask("hello")
    assert _wait(lambda: spoken == [UNREACHABLE_LINE] and states[-1] == "ready")
    v.ask("hello again")  # throttled: no new speech, but the state is restored
    states.append("thinking")  # what main.py writes on release
    v.ask("and again")
    assert _wait(lambda: states[-1] == "ready")
    assert spoken == [UNREACHABLE_LINE]
    clock[0] += 31
    v.ask("once more")
    assert _wait(lambda: spoken == [UNREACHABLE_LINE, dv.STILL_DOWN_LINE])
    assert _wait(lambda: states[-1] == "ready")
    # A successful say resets the announcement.
    client.down = False
    v.ask("back")
    client.down = True
    clock[0] += 1
    v.ask("down again")
    assert _wait(lambda: spoken[-1] == UNREACHABLE_LINE)


def test_desk_state_drives_state_file_and_tray():
    from unittest.mock import MagicMock

    from synthia.indicator import Status
    from synthia.main import Synthia

    s = Synthia.__new__(Synthia)
    s.tray = MagicMock()
    s._update_state = MagicMock()
    for state, tray in [
        ("thinking", Status.THINKING),
        ("speaking", Status.ASSISTANT),
        ("ready", Status.READY),
    ]:
        s._on_desk_state(state)
        s._update_state.assert_called_with(state)
        s.tray.set_status.assert_called_with(tray)
    s.tray = None
    s._on_desk_state("ready")  # tray disabled: no error
