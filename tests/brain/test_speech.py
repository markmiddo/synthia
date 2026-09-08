import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.cloud import speech

from synthia.brain.speech import Speech, split_for_tts


def test_split_for_tts_respects_limit_and_sentences():
    text = "One sentence here. " * 10
    parts = split_for_tts(text.strip(), limit=60)
    assert all(len(p) <= 60 for p in parts)
    assert "".join(p + " " for p in parts).strip() == text.strip()
    assert split_for_tts("short", limit=60) == ["short"]


def test_split_for_tts_hard_splits_long_sentence():
    text = "word " * 1000
    limit = 60
    chunks = split_for_tts(text.strip(), limit=limit)
    assert all(
        len(c) <= limit for c in chunks
    ), f"Found chunk longer than {limit}: {max(len(c) for c in chunks)}"
    # Verify no words are lost
    original_words = text.split()
    reconstructed_words = " ".join(chunks).split()
    assert original_words == reconstructed_words

    # Test whitespace-free token longer than limit
    text2 = "x" * 7000
    chunks2 = split_for_tts(text2, limit=3000)
    assert all(
        len(c) <= 3000 for c in chunks2
    ), f"Found chunk longer than 3000: {max(len(c) for c in chunks2)}"
    assert "".join(chunks2) == text2


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


def test_transcribe_ogg_decodes_then_recognises(tmp_path):
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"OggSfake")
    stt = FakeSTT()

    def fake_decoder(path):
        assert path == ogg
        return b"\x00\x01" * 100

    sp = Speech(
        "en-AU",
        "en-AU-Neural2-B",
        ["eventflo", "Barry"],
        stt_client=stt,
        tts_client=None,
        decoder=fake_decoder,
    )
    assert sp.transcribe_ogg(ogg) == "run the morning ritual"
    config, audio = stt.calls[0]
    assert config.language_code == "en-AU"
    assert config.encoding == speech.RecognitionConfig.AudioEncoding.LINEAR16
    assert config.sample_rate_hertz == 16000
    assert list(config.speech_contexts[0].phrases) == ["eventflo", "Barry"]
    assert audio.content == b"\x00\x01" * 100


def test_transcribe_ogg_ffmpeg_missing_raises(tmp_path):
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"OggSfake")

    def broken_decoder(path):
        raise FileNotFoundError("ffmpeg not found")

    sp = Speech("en-AU", "v", [], decoder=broken_decoder)
    with pytest.raises(RuntimeError, match="ffmpeg not found"):
        sp.transcribe_ogg(ogg)


def test_speak_to_ogg_chunks_and_writes(tmp_path):
    tts = FakeTTS()
    sp = Speech("en-AU", "en-AU-Neural2-B", [], stt_client=None, tts_client=tts)
    long_text = ("Sentence number one is here. " * 200).strip()
    files = sp.speak_to_ogg(long_text, tmp_path)
    assert len(files) >= 2
    assert all(f.suffix == ".ogg" and f.read_bytes().startswith(b"OggS") for f in files)
    assert tts.calls[0][1] == "en-AU-Neural2-B"


def test_speak_to_ogg_blank_returns_empty(tmp_path):
    tts = FakeTTS()
    sp = Speech("en-AU", "en-AU-Neural2-B", [], stt_client=None, tts_client=tts)
    files = sp.speak_to_ogg("   \n  ", tmp_path)
    assert files == []
    assert tts.calls == []


def test_transcribe_empty_result_returns_empty(tmp_path):
    class Empty:
        def recognize(self, config, audio):
            return SimpleNamespace(results=[])

    ogg = tmp_path / "n.ogg"
    ogg.write_bytes(b"x")

    def fake_decoder(path):
        return b"pcm"

    sp = Speech("en-AU", "v", [], stt_client=Empty(), decoder=fake_decoder)
    assert sp.transcribe_ogg(ogg) == ""


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    reason="needs Google credentials",
)
def test_real_google_roundtrip(tmp_path):
    sp = Speech("en-AU", "en-AU-Neural2-B", ["eventflo", "Barry"])
    files = sp.speak_to_ogg("Morning Mark. Barry ready for his walk?", tmp_path)
    assert len(files) >= 1
    transcript = sp.transcribe_ogg(files[0])
    transcript_lower = transcript.lower()
    assert "barry" in transcript_lower, f"Expected 'Barry' in transcript, got: {transcript}"
    assert "walk" in transcript_lower, f"Expected 'walk' in transcript, got: {transcript}"
