"""Speech in and out for the brain: Google Cloud STT/TTS.

Design note: Google TTS emits OGG_OPUS directly, which Telegram accepts as a voice message.
For STT the note is decoded with ffmpeg to 16 kHz mono PCM and sent as LINEAR16; sending OGG_OPUS
with a declared sample rate silently mis-transcribes when the rate does not match (measured: 48 kHz
gave garbage on Google TTS output). Clients are injectable for tests; real clients are created
lazily so importing the module never touches Google.
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

STT_SAMPLE_RATE = 16000
# A voice note is seconds of audio; anything past this means ffmpeg is stuck.
FFMPEG_TIMEOUT_S = 60
TTS_CHUNK_LIMIT = 3000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _ffmpeg_pcm16k(path: Path) -> bytes:
    """Decode OGG file to PCM 16-bit mono at 16000 Hz via ffmpeg.

    Raises RuntimeError if ffmpeg is missing or takes longer than FFMPEG_TIMEOUT_S
    (a hung decoder must not wedge the transport's worker thread forever), and
    CalledProcessError if ffmpeg itself fails.
    """
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
            timeout=FFMPEG_TIMEOUT_S,
        )
        return result.stdout
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("ffmpeg timed out") from e


def split_for_tts(text: str, limit: int = TTS_CHUNK_LIMIT) -> list[str]:
    """Split on sentence ends so each chunk is at most `limit` characters.

    Hard-splits any single sentence/word longer than limit on whitespace or at character boundaries.
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
            for word in words:
                # If word itself is longer than limit, clip it into chunks
                if len(word) > limit:
                    while len(word) > limit:
                        sentence_chunks.append(word[:limit])
                        word = word[limit:]
                    if word:
                        sentence_chunks.append(word)
                else:
                    sentence_chunks.append(word)
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
        with phrase hints. Raises google.api_core.exceptions.GoogleAPIError on API failure,
        RuntimeError if ffmpeg is missing, and subprocess.CalledProcessError when ffmpeg
        fails to decode (corrupt audio); callers handle all.
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
