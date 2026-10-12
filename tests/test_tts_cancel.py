"""cancel() must stop a speak() call wherever it is: lock wait, synthesis, or before a Popen."""

import threading
import time
from types import SimpleNamespace

import pytest

from synthia import tts as tts_module
from synthia.tts import TextToSpeech


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_module, "SPEECH_LOCK_PATH", str(tmp_path / "tts.lock"))
    monkeypatch.setattr(tts_module, "is_voice_muted", lambda: False)
    spawned = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            spawned.append(cmd[0])
            self.stdout = None
            self.stdin = None
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self):
            return 0

        def terminate(self):
            pass

    monkeypatch.setattr(tts_module.subprocess, "Popen", FakePopen)
    return spawned


def _piper():
    t = TextToSpeech(use_local=True)
    return t


def test_cancel_during_the_speech_lock_wait_is_not_lost(_isolated):
    t = _piper()
    result = []
    with tts_module.speech_lock() as held:
        assert held
        worker = threading.Thread(target=lambda: result.append(t.speak("Hello there, friend.")))
        worker.start()
        time.sleep(0.3)  # the worker is now blocked behind our lock
        t.cancel()
    worker.join(5)
    assert result == [False]
    assert _isolated == []


def test_cancel_during_google_synthesis_never_starts_mpv(_isolated, monkeypatch):
    t = TextToSpeech.__new__(TextToSpeech)
    t.use_local = False
    t.speed = 1.0
    t.voice_name = "en-US-Neural2-J"
    t.language_code = "en-US"
    t._playback = None
    t._synth = None
    t._gen = 0
    t._gen_lock = threading.Lock()

    def synthesize_speech(**kw):
        t.cancel()  # lands while the round trip is in flight
        return SimpleNamespace(audio_content=b"mp3")

    t.client = SimpleNamespace(synthesize_speech=synthesize_speech)
    fake_tts = SimpleNamespace(
        VoiceSelectionParams=lambda **kw: None,
        AudioConfig=lambda **kw: None,
        SynthesisInput=lambda **kw: None,
        AudioEncoding=SimpleNamespace(MP3=1),
    )
    monkeypatch.setitem(__import__("sys").modules, "google.cloud.texttospeech", fake_tts)
    import google.cloud

    monkeypatch.setattr(google.cloud, "texttospeech", fake_tts, raising=False)
    assert t.speak("Hello there, friend.") is False
    assert _isolated == []


def test_a_cancel_before_a_new_speak_does_not_silence_it(_isolated):
    t = _piper()
    t.cancel()
    assert t.speak("Hello there, friend.") is True
    assert _isolated == ["piper", "aplay"]


def test_background_mute_silences_speech_but_not_a_direct_reply(_isolated, monkeypatch):
    monkeypatch.setattr(tts_module, "is_voice_muted", lambda: True)
    t = _piper()
    assert t.speak("An agent finished.") is False
    assert _isolated == []
    assert t.speak("Here's what's going on.", ignore_mute=True) is True
    assert _isolated == ["piper", "aplay"]
