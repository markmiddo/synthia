"""Google Cloud Speech-to-Text integration."""

import os
from google.cloud import speech


class Transcriber:
    """Transcribes audio using Google Cloud Speech-to-Text."""

    def __init__(self, credentials_path: str, language: str = "en-US", sample_rate: int = 16000):
        # Set credentials environment variable
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self.client = speech.SpeechClient()
        self.language = language
        self.sample_rate = sample_rate

        self.config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=language,
            enable_automatic_punctuation=True,
            diarization_config=None,
            metadata=speech.RecognitionMetadata(
                interaction_type=speech.RecognitionMetadata.InteractionType.DICTATION,
            ),
        )

        # Post-process to remove filler words
        self.filler_words = {'uh', 'um', 'ah', 'er', 'hmm', 'uh,', 'um,', 'ah,', 'er,'}

    def transcribe(self, audio_data: bytes) -> str:
        """Transcribe audio bytes to text."""
        if not audio_data:
            return ""

        audio = speech.RecognitionAudio(content=audio_data)

        print("🔄 Transcribing...")

        try:
            response = self.client.recognize(config=self.config, audio=audio)

            if not response.results:
                print("⚠️  No transcription results")
                return ""

            # Concatenate all transcription results
            transcript = " ".join(
                result.alternatives[0].transcript
                for result in response.results
                if result.alternatives
            )

            # Remove filler words
            words = transcript.split()
            cleaned = ' '.join(w for w in words if w.lower().rstrip('.,!?') not in self.filler_words)

            print(f"📝 Transcribed: {cleaned}")
            return cleaned

        except Exception as e:
            print(f"❌ Transcription error: {e}")
            return ""
