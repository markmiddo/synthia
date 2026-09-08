"""Speech in and out for the brain: Google Cloud STT/TTS, OGG_OPUS out, ffmpeg-decoded PCM in."""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

STT_SAMPLE_RATE = 16000
TTS_CHUNK_LIMIT = 3000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _ffmpeg_pcm16k(path: Path) -> bytes:
    """Decode OGG file to PCM 16-bit mono at 16000 Hz via ffmpeg."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found") from e


def split_for_tts(text: str, limit: int = TTS_CHUNK_LIMIT) -> list[str]:
    """Split on sentence ends so each chunk is at most `limit` characters.

    Hard-splits any single sentence longer than limit on whitespace.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for sentence in _SENTENCE_END.split(text):
        # If sentence itself is too long, hard-split it first
        if len(sentence) > limit:
            # Hard-split sentence on whitespace
            words = sentence.split()
            sentence_chunks = []
            word_group = ""
            for word in words:
                test = f"{word_group} {word}".strip()
                if len(test) <= limit:
                    word_group = test
                else:
                    if word_group:
                        sentence_chunks.append(word_group)
                    word_group = word
            if word_group:
                sentence_chunks.append(word_group)
            sentence = " ".join(sentence_chunks)
            sentences_to_add = sentence_chunks
        else:
            sentences_to_add = [sentence]

        # Add sentences to chunks
        for sent in sentences_to_add:
            if current and len(current) + 1 + len(sent) > limit:
                chunks.append(current)
                current = sent
            else:
                current = f"{current} {sent}".strip()

    if current:
        chunks.append(current)

    return chunks if chunks else [text]


class Speech:
    def __init__(
        self,
        language: str,
        voice: str,
        phrase_hints: list[str],
        stt_client: Any | None = None,
        tts_client: Any | None = None,
        decoder: Callable[[Path], bytes] | None = None,
    ) -> None:
        self.language = language
        self.voice = voice
        self.phrase_hints = list(phrase_hints)
        self._stt = stt_client
        self._tts = tts_client
        self._decoder = decoder or _ffmpeg_pcm16k

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
        """Transcribe OGG_OPUS voice note to text.

        Decodes via ffmpeg to PCM 16-bit mono at 16000 Hz, then uses Google Speech-to-Text
        with phrase hints. Raises google.api_core.exceptions.GoogleAPIError on API failure
        and RuntimeError if ffmpeg is missing; callers handle both.
        """
        from google.cloud import speech

        try:
            pcm = self._decoder(path)
        except FileNotFoundError as e:
            raise RuntimeError("ffmpeg not found") from e

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=STT_SAMPLE_RATE,
            language_code=self.language,
            enable_automatic_punctuation=True,
            speech_contexts=[speech.SpeechContext(phrases=self.phrase_hints)],
        )
        audio = speech.RecognitionAudio(content=pcm)
        response = self._stt_client().recognize(config=config, audio=audio)
        text = " ".join(
            r.alternatives[0].transcript for r in response.results if r.alternatives
        ).strip()
        logger.info("Transcribed %d chars", len(text))
        return text

    # ---- TTS ----

    def speak_to_ogg(self, text: str, out_dir: Path) -> list[Path]:
        """Synthesize text to OGG_OPUS files, chunked at sentence boundaries.

        Returns list of Path objects to generated .ogg files. If text is blank,
        returns empty list. Raises google.api_core.exceptions.GoogleAPIError on
        API failure; callers handle it.
        """
        if not text.strip():
            return []

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
