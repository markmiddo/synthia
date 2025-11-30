"""Speech-to-Text integration with Google Cloud and local Whisper options."""

import os
import tempfile
import numpy as np


class Transcriber:
    """Transcribes audio using Google Cloud Speech-to-Text or local Whisper."""

    def __init__(self, credentials_path: str = None, language: str = "en-US",
                 sample_rate: int = 16000, use_local: bool = False,
                 local_model: str = "small"):
        self.language = language
        self.sample_rate = sample_rate
        self.use_local = use_local
        self.local_model = local_model
        self.whisper_model = None
        self.client = None

        # Post-process to remove filler words
        self.filler_words = {'uh', 'um', 'ah', 'er', 'hmm', 'uh,', 'um,', 'ah,', 'er,'}

        if use_local:
            self._init_whisper()
        else:
            self._init_google(credentials_path)

    def _init_google(self, credentials_path: str):
        """Initialize Google Cloud Speech-to-Text."""
        from google.cloud import speech

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
        print(f"Google STT initialized")

    def _init_whisper(self):
        """Initialize local Whisper model using faster-whisper."""
        from faster_whisper import WhisperModel

        # Use tiny model on CPU for fastest response
        model_name = "tiny"  # tiny is fastest, ~1s transcription
        print(f"Loading faster-whisper model: {model_name}...")
        self.whisper_model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=4
        )
        print(f"Faster-whisper {model_name} loaded (CPU int8)")

    def transcribe(self, audio_data: bytes) -> str:
        """Transcribe audio bytes to text."""
        if not audio_data:
            return ""

        print("Transcribing...")

        try:
            if self.use_local:
                return self._transcribe_whisper(audio_data)
            else:
                return self._transcribe_google(audio_data)
        except Exception as e:
            print(f"Transcription error: {e}")
            return ""

    def _transcribe_google(self, audio_data: bytes) -> str:
        """Transcribe using Google Cloud STT."""
        from google.cloud import speech

        audio = speech.RecognitionAudio(content=audio_data)

        response = self.client.recognize(config=self.config, audio=audio)

        if not response.results:
            print("No transcription results")
            return ""

        # Concatenate all transcription results
        transcript = " ".join(
            result.alternatives[0].transcript
            for result in response.results
            if result.alternatives
        )

        # Remove filler words
        cleaned = self._clean_transcript(transcript)
        print(f"Transcribed: {cleaned}")
        return cleaned

    def _transcribe_whisper(self, audio_data: bytes) -> str:
        """Transcribe using faster-whisper model."""
        # Convert bytes to numpy array (16-bit signed int)
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        # faster-whisper returns segments generator
        segments, info = self.whisper_model.transcribe(
            audio_np,
            language="en",
            beam_size=1,  # Faster with beam_size=1
            vad_filter=True,  # Filter out silence
        )

        # Collect all segments
        transcript = " ".join(segment.text for segment in segments).strip()

        # Remove filler words
        cleaned = self._clean_transcript(transcript)
        print(f"Transcribed: {cleaned}")
        return cleaned

    def _clean_transcript(self, transcript: str) -> str:
        """Remove filler words from transcript."""
        words = transcript.split()
        cleaned = ' '.join(w for w in words if w.lower().rstrip('.,!?') not in self.filler_words)
        return cleaned
