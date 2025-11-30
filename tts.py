"""Google Cloud Text-to-Speech integration with streaming."""

import os
import subprocess
import tempfile
import threading
from google.cloud import texttospeech


class TextToSpeech:
    """Converts text to speech using Google Cloud TTS with streaming playback."""

    def __init__(self, credentials_path: str, voice_name: str = "en-US-Neural2-J", speed: float = 1.0):
        # Set credentials environment variable
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self.client = texttospeech.TextToSpeechClient()
        self.voice_name = voice_name
        self.speed = speed

        # Extract language code from voice name (e.g., "en-US" from "en-US-Neural2-J")
        self.language_code = "-".join(voice_name.split("-")[:2])

        print(f"🔊 TTS initialized with voice: {voice_name}")

    def _split_into_chunks(self, text: str, max_chars: int = 200) -> list:
        """Split text into smaller chunks for streaming effect."""
        sentences = []
        current = ""

        # Split by sentence endings
        for char in text:
            current += char
            if char in '.!?' and len(current) >= 20:
                sentences.append(current.strip())
                current = ""

        if current.strip():
            sentences.append(current.strip())

        # If we got sentences, return them
        if sentences:
            return sentences

        # Fallback: split by max_chars at word boundaries
        words = text.split()
        chunks = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > max_chars:
                if current:
                    chunks.append(current.strip())
                current = word
            else:
                current = current + " " + word if current else word
        if current:
            chunks.append(current.strip())

        return chunks if chunks else [text]

    def speak(self, text: str) -> bool:
        """Convert text to speech and play it with streaming for faster response."""
        if not text:
            return False

        try:
            print(f"🗣️  Speaking: {text[:50]}{'...' if len(text) > 50 else ''}")

            # For short text, just speak directly
            if len(text) < 150:
                return self._speak_chunk(text)

            # For longer text, split into chunks and stream
            chunks = self._split_into_chunks(text)

            # Start generating first chunk immediately
            for i, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue

                # Generate and play each chunk
                if not self._speak_chunk(chunk):
                    return False

            return True

        except Exception as e:
            print(f"❌ TTS error: {e}")
            return False

    def _speak_chunk(self, text: str) -> bool:
        """Speak a single chunk of text."""
        try:
            # Set up the voice parameters
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.language_code,
                name=self.voice_name,
            )

            # Set up the audio config
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=self.speed,
            )

            # Build the synthesis input
            synthesis_input = texttospeech.SynthesisInput(text=text)

            # Perform the text-to-speech request
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

            # Save to temp file and play with mpv
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(response.audio_content)
                temp_path = f.name

            # Play with mpv (quiet mode, no video)
            subprocess.run(
                ["mpv", "--no-video", "--really-quiet", temp_path],
                check=True,
            )

            # Clean up temp file
            os.unlink(temp_path)

            return True

        except Exception as e:
            print(f"❌ TTS chunk error: {e}")
            return False

    def stop(self):
        """Stop any currently playing audio."""
        subprocess.run(["pkill", "-f", "mpv"], check=False)
