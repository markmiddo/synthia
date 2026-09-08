from pathlib import Path
from types import SimpleNamespace

from synthia.brain.speech import Speech, split_for_tts


def test_split_for_tts_respects_limit_and_sentences():
    text = "One sentence here. " * 10
    parts = split_for_tts(text.strip(), limit=60)
    assert all(len(p) <= 60 for p in parts)
    assert "".join(p + " " for p in parts).strip() == text.strip()
    assert split_for_tts("short", limit=60) == ["short"]


class FakeSTT:
    def __init__(self):
        self.calls = []

    def recognize(self, config, audio):
        self.calls.append((config, audio))
        alt = SimpleNamespace(transcript="run the morning ritual")
        return SimpleNamespace(results=[SimpleNamespace(alternatives=[alt])])


class FakeTTS:
    def __init__(self):
        self.calls = []

    def synthesize_speech(self, input, voice, audio_config):
        self.calls.append((input.text, voice.name, audio_config.audio_encoding))
        return SimpleNamespace(audio_content=b"OggS" + input.text.encode())


def test_transcribe_ogg_uses_opus_and_hints(tmp_path):
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"OggSfake")
    stt = FakeSTT()
    sp = Speech("en-AU", "en-AU-Neural2-B", ["eventflo", "Barry"], stt_client=stt, tts_client=None)
    assert sp.transcribe_ogg(ogg) == "run the morning ritual"
    config, audio = stt.calls[0]
    assert config.language_code == "en-AU"
    assert config.sample_rate_hertz == 48000
    assert list(config.speech_contexts[0].phrases) == ["eventflo", "Barry"]
    assert audio.content == b"OggSfake"


def test_speak_to_ogg_chunks_and_writes(tmp_path):
    tts = FakeTTS()
    sp = Speech("en-AU", "en-AU-Neural2-B", [], stt_client=None, tts_client=tts)
    long_text = ("Sentence number one is here. " * 200).strip()
    files = sp.speak_to_ogg(long_text, tmp_path)
    assert len(files) >= 2
    assert all(f.suffix == ".ogg" and f.read_bytes().startswith(b"OggS") for f in files)
    assert tts.calls[0][1] == "en-AU-Neural2-B"


def test_transcribe_empty_result_returns_empty(tmp_path):
    class Empty:
        def recognize(self, config, audio):
            return SimpleNamespace(results=[])

    ogg = tmp_path / "n.ogg"
    ogg.write_bytes(b"x")
    sp = Speech("en-AU", "v", [], stt_client=Empty(), tts_client=None)
    assert sp.transcribe_ogg(ogg) == ""
