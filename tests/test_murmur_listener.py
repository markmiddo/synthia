"""Murmur listener: signal mapping, outage notice, recovery, config, no Whisper."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

from synthia import murmur_listener as ml
from synthia.config import validate_config
from synthia.murmur_listener import MurmurListener, MurmurUnavailable


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakeBus:
    """A scripted bus: events are handed out in order, then it idles."""

    def __init__(self, owner=True, events=None, hotkey="Left Alt"):
        self.owner = owner
        self.events = list(events or [])
        self._hotkey = hotkey
        self.subscribed = False
        self.closed = False

    def has_owner(self):
        return self.owner

    def subscribe(self):
        self.subscribed = True

    def hotkey(self):
        if isinstance(self._hotkey, Exception):
            raise self._hotkey
        return self._hotkey

    def next_event(self, timeout):
        if self.events:
            return self.events.pop(0)
        time.sleep(min(timeout, 0.01))
        return None

    def close(self):
        self.closed = True


def _listener(buses, **kw):
    """A listener over a queue of fake buses; records every callback."""
    calls: list[Any] = []
    q = list(buses)

    def factory():
        item = q.pop(0) if len(q) > 1 else q[0]
        if isinstance(item, Exception):
            raise item
        return item

    ln = MurmurListener(
        on_started=lambda: calls.append(("started",)),
        on_transcribed=lambda t, at: calls.append(("transcribed", t, at)),
        on_cancelled=lambda: calls.append(("cancelled",)),
        on_unavailable=lambda: calls.append(("unavailable",)),
        on_hotkey=lambda k: calls.append(("hotkey", k)),
        bus_factory=factory,
        retry_seconds=0.02,
        poll_seconds=0.01,
        clock=lambda: 42.0,
        **kw,
    )
    return ln, calls


def test_signals_map_to_callbacks():
    bus = FakeBus(
        events=[
            ("AssistantStarted", ()),
            ("AssistantTranscribed", ("what time is it",)),
            ("AssistantTranscribed", ("",)),
            ("AssistantCancelled", ()),
        ]
    )
    ln, calls = _listener([bus])
    ln.start()
    assert _wait(lambda: ("cancelled",) in calls)
    ln.stop()
    assert calls == [
        ("hotkey", "Left Alt"),
        ("started",),
        ("transcribed", "what time is it", 42.0),
        ("transcribed", "", 42.0),
        ("cancelled",),
    ]
    assert bus.subscribed and bus.closed


def test_handler_error_does_not_drop_subscription():
    bus = FakeBus(events=[("AssistantStarted", ()), ("AssistantCancelled", ())])
    seen: list[str] = []

    def boom():
        raise RuntimeError("bad")

    ln = MurmurListener(
        on_started=boom,
        on_transcribed=lambda t, at: None,
        on_cancelled=lambda: seen.append("cancelled"),
        on_unavailable=lambda: None,
        bus_factory=lambda: bus,
        retry_seconds=0.02,
        poll_seconds=0.01,
    )
    ln.start()
    assert _wait(lambda: seen == ["cancelled"])
    ln.stop()


def test_absent_murmur_notices_once_retries_and_recovers():
    absent = FakeBus(owner=False)
    present = FakeBus(events=[("AssistantStarted", ())])
    ln, calls = _listener([absent, absent, absent, present])
    ln.start()
    assert _wait(lambda: ("started",) in calls)
    ln.stop()
    assert calls.count(("unavailable",)) == 1  # one spoken notice, however many retries
    assert calls.index(("unavailable",)) < calls.index(("started",))
    assert ("hotkey", "Left Alt") in calls  # hotkey read once it came back


def test_bus_connect_failure_never_raises_and_recovers():
    ln, calls = _listener([OSError("no session bus"), FakeBus(events=[("AssistantStarted", ())])])
    ln.start()
    assert _wait(lambda: ("started",) in calls)
    ln.stop()
    assert calls.count(("unavailable",)) == 1


def test_murmur_going_away_mid_session_announces_then_recovers():
    first = FakeBus(events=[("OwnerChanged", ("",))])
    second = FakeBus(events=[("AssistantStarted", ())])
    ln, calls = _listener([first, second])
    ln.start()
    assert _wait(lambda: ("started",) in calls)
    ln.stop()
    assert calls.count(("unavailable",)) == 1
    assert first.closed


def test_second_outage_is_announced_again():
    a = FakeBus(owner=False)
    b = FakeBus(events=[("OwnerChanged", ("",))])
    c = FakeBus(owner=False)
    d = FakeBus(events=[("AssistantStarted", ())])
    ln, calls = _listener([a, b, c, d])
    ln.start()
    assert _wait(lambda: ("started",) in calls)
    ln.stop()
    assert calls.count(("unavailable",)) == 2


def test_hotkey_label_tracks_property_changes_and_empty_means_off():
    bus = FakeBus(hotkey="", events=[("PropertiesChanged", ("io.github.markmiddo.Murmur1",))])
    ln, calls = _listener([bus])
    ln.start()
    assert _wait(lambda: calls.count(("hotkey", "")) == 2)
    ln.stop()


def test_old_murmur_without_the_property_gives_unknown_hotkey():
    bus = FakeBus(hotkey=MurmurUnavailable("Unknown property"))
    ln, calls = _listener([bus])
    ln.start()
    assert _wait(lambda: ("hotkey", None) in calls)
    ln.stop()


def test_murmur_unavailable_error_type():
    assert issubclass(MurmurUnavailable, Exception)
    assert ml.UNAVAILABLE_LINE == "I can't hear you, Murmur isn't running."


# ---- Synthia wiring -------------------------------------------------------------


def _synthia(**over):
    from synthia.main import Synthia

    s = Synthia.__new__(Synthia)
    s.running = True
    s.assistant_active = False
    s.desk_voice = MagicMock()
    s.tray = MagicMock()
    s._update_state = MagicMock()
    s._save_to_history = MagicMock()
    s.tts = MagicMock()
    s.talk_key = None
    s._last_status = "ready"
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_started_is_a_key_press():
    from synthia.indicator import Status

    s = _synthia()
    s._on_murmur_started()
    s.desk_voice.begin_utterance.assert_called_once_with()
    s._update_state.assert_called_with("recording")
    s.tray.set_status.assert_called_with(Status.RECORDING)
    assert s.assistant_active


def test_transcribed_asks_with_arrival_time():
    s = _synthia(assistant_active=True)
    s._on_murmur_transcribed("  open the pod bay doors ", 7.5)
    s.desk_voice.ask.assert_called_once_with("open the pod bay doors", released_at=7.5)
    s.desk_voice.end_utterance.assert_not_called()
    assert not s.assistant_active


def test_empty_transcript_and_cancel_end_the_utterance():
    s = _synthia()
    s._on_murmur_transcribed("", 1.0)
    s.desk_voice.ask.assert_not_called()
    s.desk_voice.end_utterance.assert_called_once_with()
    s.desk_voice.reset_mock()
    s._on_murmur_cancelled()
    s.desk_voice.end_utterance.assert_called_once_with()


def test_unavailable_speaks_the_line():
    s = _synthia()
    s._on_murmur_unavailable()
    assert _wait(lambda: s.tts.speak.called)
    s.tts.speak.assert_called_with(ml.UNAVAILABLE_LINE, ignore_mute=True)


def test_hotkey_label_lands_in_state_file():
    s = _synthia(_last_status="thinking")
    s._on_murmur_hotkey("Left Alt")
    assert s.talk_key == "Left Alt"
    s._update_state.assert_called_with("thinking")
    s._update_state.reset_mock()
    s._on_murmur_hotkey("Left Alt")  # unchanged: no rewrite
    s._update_state.assert_not_called()


# ---- config + Whisper -----------------------------------------------------------


def test_stt_source_validation():
    assert validate_config({"stt_source": "murmur", "assistant_backend": "brain"}) == []
    assert validate_config({"stt_source": "synthia"}) == []
    assert any("stt_source" in w for w in validate_config({"stt_source": "bogus"}))
    assert any(
        "assistant_backend" in w
        for w in validate_config({"stt_source": "murmur", "assistant_backend": "local"})
    )


def test_needs_local_stt_rules():
    from synthia.main import needs_local_stt, use_murmur_stt

    base = {"assistant_backend": "brain", "stt_source": "murmur", "dictation_key": "none"}
    assert use_murmur_stt(base) and not needs_local_stt(base)
    assert needs_local_stt({**base, "dictation_key": "Key.ctrl_r"})
    assert needs_local_stt({**base, "stt_source": "synthia"})
    assert needs_local_stt({**base, "assistant_backend": "local"})  # murmur ignored


def _config(**over):
    from synthia.config import DEFAULT_CONFIG

    return {
        **DEFAULT_CONFIG,
        "assistant_backend": "brain",
        "use_local_tts": True,
        "use_llm_polish": False,
        "show_notifications": False,
        "clipboard_history_enabled": False,
        **over,
    }


def test_murmur_mode_loads_no_whisper_and_registers_no_assistant_key(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import synthia.main as m

    cfg = _config(stt_source="murmur", dictation_key="none")
    with patch.object(m, "Transcriber") as tr, patch.object(m, "AudioRecorder") as rec:
        s, _ = _build_with(cfg, tr, rec)
    tr.assert_not_called()
    rec.assert_not_called()
    assert s.transcriber is None and s.recorder is None
    assert s.murmur is not None


def _build_with(config, transcriber, recorder):
    import synthia.main as m

    with patch.multiple(
        m,
        load_config=MagicMock(return_value=config),
        get_google_credentials_path=MagicMock(return_value=None),
        get_anthropic_api_key=MagicMock(return_value=None),
        SoundEffects=MagicMock(),
        TextToSpeech=MagicMock(),
        Assistant=MagicMock(),
        AckBank=MagicMock(),
        DeskVoice=MagicMock(),
        BrainClient=MagicMock(),
        TranscriptionPolisher=MagicMock(),
        ClipboardMonitor=MagicMock(),
        create_hotkey_listener=MagicMock(),
        MurmurListener=MagicMock(),
        notify_ready=MagicMock(),
    ):
        s = m.Synthia()
        s.created_with = m.create_hotkey_listener.call_args
        return s, m


def test_murmur_mode_passes_no_assistant_key_to_the_hotkey_listener(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import synthia.main as m

    cfg = _config(stt_source="murmur", dictation_key="none")
    with patch.object(m, "Transcriber") as tr, patch.object(m, "AudioRecorder") as rec:
        s, _ = _build_with(cfg, tr, rec)
    assert s.created_with.kwargs["assistant_key_string"] == "none"


def test_synthia_mode_still_loads_whisper(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import synthia.main as m

    cfg = _config(stt_source="synthia", dictation_key="none")
    with patch.object(m, "Transcriber") as tr, patch.object(m, "AudioRecorder") as rec:
        s, _ = _build_with(cfg, tr, rec)
    tr.assert_called_once()
    rec.assert_called_once()
    assert s.murmur is None
    assert s.created_with.kwargs["assistant_key_string"] == cfg["assistant_key"]


def test_murmur_mode_with_dictation_on_keeps_the_transcriber(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import synthia.main as m

    cfg = _config(stt_source="murmur", dictation_key="Key.ctrl_r")
    with patch.object(m, "Transcriber") as tr, patch.object(m, "AudioRecorder") as rec:
        s, _ = _build_with(cfg, tr, rec)
    tr.assert_called_once()
    assert s.murmur is not None


def test_state_file_carries_stt_source_and_talk_key(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import synthia.main as m

    cfg = _config(stt_source="murmur", dictation_key="none")
    with patch.object(m, "Transcriber") as tr, patch.object(m, "AudioRecorder") as rec:
        s, _ = _build_with(cfg, tr, rec)
    s._on_murmur_hotkey("Left Alt")
    state = json.loads((tmp_path / "synthia-state.json").read_text())
    assert state["stt_source"] == "murmur" and state["talk_key"] == "Left Alt"
    s._on_murmur_hotkey("")
    assert json.loads((tmp_path / "synthia-state.json").read_text())["talk_key"] == ""
