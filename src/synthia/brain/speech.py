"""Speech in and out for the brain: Google Cloud STT/TTS, Opus ogg both ways."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TELEGRAM_OPUS_RATE = 48000
TTS_CHUNK_LIMIT = 3000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_for_tts(text: str, limit: int = TTS_CHUNK_LIMIT) -> list[str]:
    """Split on sentence ends so each chunk is at most `limit` characters."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


class Speech:
    def __init__(
        self,
        language: str,
        voice: str,
        phrase_hints: list[str],
        stt_client: Any | None = None,
        tts_client: Any | None = None,
    ) -> None:
        self.language = language
        self.voice = voice
        self.phrase_hints = list(phrase_hints)
        self._stt = stt_client
        self._tts = tts_client

    # ---- lazy real clients ----

    def _stt_client(self) -> Any:
        if self._stt is None:
            from google.cloud import speech

            self._stt = speech.SpeechClient()
        return self._stt

    def _tts_client(self) -> Any:
        if self._tts is None:
            from google.cloud import texttospeech

            self._tts = texttospeech.TextToSpeechClient()
        return self._tts

    # ---- STT ----

    def transcribe_ogg(self, path: Path) -> str:
        from google.cloud import speech

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=TELEGRAM_OPUS_RATE,
            language_code=self.language,
            enable_automatic_punctuation=True,
            speech_contexts=[speech.SpeechContext(phrases=self.phrase_hints)],
        )
        audio = speech.RecognitionAudio(content=path.read_bytes())
        response = self._stt_client().recognize(config=config, audio=audio)
        text = " ".join(
            r.alternatives[0].transcript for r in response.results if r.alternatives
        ).strip()
        logger.info("Transcribed %d chars", len(text))
        return text

    # ---- TTS ----

    def speak_to_ogg(self, text: str, out_dir: Path) -> list[Path]:
        from google.cloud import texttospeech

        out_dir.mkdir(parents=True, exist_ok=True)
        voice = texttospeech.VoiceSelectionParams(
            language_code="-".join(self.voice.split("-")[:2]), name=self.voice
        )
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.OGG_OPUS)
        files: list[Path] = []
        for chunk in split_for_tts(text):
            response = self._tts_client().synthesize_speech(
                input=texttospeech.SynthesisInput(text=chunk),
                voice=voice,
                audio_config=audio_config,
            )
            path = out_dir / f"{uuid.uuid4().hex}.ogg"
            path.write_bytes(response.audio_content)
            files.append(path)
        return files
