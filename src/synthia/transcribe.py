"""Speech-to-Text integration with Google Cloud and local Whisper options."""

from __future__ import annotations

import logging
import os
import sys
import tempfile

import numpy as np

logger = logging.getLogger(__name__)

# Add cuDNN libraries to path for GPU support
_cudnn_path = os.path.join(
    os.path.dirname(__file__),
    f"venv/lib/python{sys.version_info.major}.{sys.version_info.minor}"
    "/site-packages/nvidia/cudnn/lib",
)
if os.path.exists(_cudnn_path):
    os.environ["LD_LIBRARY_PATH"] = _cudnn_path + ":" + os.environ.get("LD_LIBRARY_PATH", "")


class Transcriber:
    """Transcribes audio using Google Cloud Speech-to-Text or local Whisper."""

    def __init__(
        self,
        credentials_path: str | None = None,
        language: str = "en-US",
        sample_rate: int = 16000,
        use_local: bool = False,
        local_model: str = "small",
    ) -> None:
        self.language = language
        self.sample_rate = sample_rate
        self.use_local = use_local
        self.local_model = local_model
        self.whisper_model = None
        self.client = None

        # Post-process to remove filler words
        self.filler_words = {"uh", "um", "ah", "er", "hmm", "uh,", "um,", "ah,", "er,"}

        if use_local:
            self._init_whisper()
        else:
            self._init_google(credentials_path)

    def _init_google(self, credentials_path: str | None) -> None:
        """Initialize Google Cloud Speech-to-Text."""
        from google.cloud import speech

        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        self.client = speech.SpeechClient()

        self.config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            language_code=self.language,
            enable_automatic_punctuation=True,
            diarization_config=None,
            metadata=speech.RecognitionMetadata(
                interaction_type=speech.RecognitionMetadata.InteractionType.DICTATION,
            ),
        )
        logger.info("Google STT initialized")

    def _init_whisper(self) -> None:
        """Initialize local Whisper model using faster-whisper."""
        from faster_whisper import WhisperModel

        model_name = self.local_model
        logger.info("Loading faster-whisper model: %s...", model_name)

        # Use CPU - GPU inference produces garbage with current cuDNN version
        # TODO: Re-enable GPU after upgrading ctranslate2 + matching cuDNN
        self.whisper_model = WhisperModel(
            model_name, device="cpu", compute_type="int8", cpu_threads=4
        )
        logger.info("Faster-whisper %s loaded (CPU int8)", model_name)

    def transcribe(self, audio_data: bytes) -> str:
        """Transcribe audio bytes to text."""
        if not audio_data:
            return ""

        logger.debug("Transcribing...")

        try:
            if self.use_local:
                return self._transcribe_whisper(audio_data)
            else:
                return self._transcribe_google(audio_data)
        except Exception as e:
            logger.error("Transcription error: %s", e)
            return ""

    def _transcribe_google(self, audio_data: bytes) -> str:
        """Transcribe using Google Cloud STT."""
        from google.cloud import speech

        audio = speech.RecognitionAudio(content=audio_data)

        assert self.client is not None
        response = self.client.recognize(config=self.config, audio=audio)

        if not response.results:
            logger.debug("No transcription results")
            return ""

        # Concatenate all transcription results
        transcript = " ".join(
            result.alternatives[0].transcript for result in response.results if result.alternatives
        )

        # Remove filler words
        cleaned = self._clean_transcript(transcript)
        logger.info("Transcribed: %s", cleaned)
        return cleaned

    def _transcribe_whisper(self, audio_data: bytes) -> str:
        """Transcribe using faster-whisper model."""
        # Convert bytes to numpy array (16-bit signed int)
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Skip very short audio (< 0.5 seconds) to avoid hallucinations
        duration = len(audio_np) / self.sample_rate
        if duration < 0.5:
            logger.debug("Audio too short (%.2fs), skipping", duration)
            return ""

        # Check audio level - skip if too quiet (likely no speech)
        rms = np.sqrt(np.mean(audio_np**2))
        if rms < 0.005:
            logger.debug("Audio too quiet (rms=%.4f), skipping", rms)
            return ""

        # faster-whisper returns segments generator
        assert self.whisper_model is not None
        segments, info = self.whisper_model.transcribe(
            audio_np,
            language="en",
            beam_size=1,  # Faster with beam_size=1
            vad_filter=True,  # Filter out silence
            no_speech_threshold=0.6,  # Skip segments likely without speech
            hallucination_silence_threshold=1.0,  # Skip hallucinated silence
            condition_on_previous_text=False,  # Prevent hallucination loops
        )

        # Collect segments with a max token limit to prevent runaway generation
        parts = []
        for segment in segments:
            parts.append(segment.text)
            if len(parts) > 50:  # Safety limit
                logger.warning("Hit segment limit, stopping transcription")
                break
        transcript = " ".join(parts).strip()

        # Reject hallucinated output (repetitive single characters)
        if len(transcript) > 10 and len(set(transcript.replace(" ", ""))) <= 2:
            logger.warning("Rejected hallucinated output: %s...", transcript[:30])
            return ""

        # Remove filler words
        cleaned = self._clean_transcript(transcript)
        logger.info("Transcribed: %s", cleaned)
        return cleaned

    def _clean_transcript(self, transcript: str) -> str:
        """Remove filler words from transcript."""
        words = transcript.split()
        cleaned = " ".join(w for w in words if w.lower().rstrip(".,!?") not in self.filler_words)
        return cleaned
