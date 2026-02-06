"""Text-to-Speech integration with Google Cloud and local Piper options."""

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class TextToSpeech:
    """Converts text to speech using Google Cloud TTS or local Piper."""

    def __init__(
        self,
        credentials_path: str = None,
        voice_name: str = "en-US-Neural2-J",
        speed: float = 1.0,
        use_local: bool = False,
        local_voice: str = "~/.local/share/piper-voices/en_US-amy-medium.onnx",
    ):
        self.use_local = use_local
        self.speed = speed
        self.voice_name = voice_name
        self.local_voice = os.path.expanduser(local_voice)
        self.client = None

        if use_local:
            logger.info("Piper TTS initialized with voice: %s", os.path.basename(self.local_voice))
        else:
            self._init_google(credentials_path, voice_name)

    def _init_google(self, credentials_path: str, voice_name: str):
        """Initialize Google Cloud TTS."""
        from google.cloud import texttospeech

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        self.client = texttospeech.TextToSpeechClient()
        self.voice_name = voice_name
        self.language_code = "-".join(voice_name.split("-")[:2])
        logger.info("Google TTS initialized with voice: %s", voice_name)

    def _split_into_chunks(self, text: str, max_chars: int = 200) -> list:
        """Split text into smaller chunks for streaming effect."""
        sentences = []
        current = ""

        # Split by sentence endings
        for char in text:
            current += char
            if char in ".!?" and len(current) >= 20:
                sentences.append(current.strip())
                current = ""

        if current.strip():
            sentences.append(current.strip())

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
        """Convert text to speech and play it."""
        if not text:
            return False

        try:
            logger.debug("Speaking: %s%s", text[:50], "..." if len(text) > 50 else "")

            if self.use_local:
                return self._speak_piper(text)

            # For Google TTS, use chunking for longer text
            if len(text) < 150:
                return self._speak_google_chunk(text)

            chunks = self._split_into_chunks(text)
            for chunk in chunks:
                if chunk.strip() and not self._speak_google_chunk(chunk):
                    return False
            return True

        except Exception as e:
            logger.error("TTS error: %s", e)
            return False

    def _speak_piper(self, text: str) -> bool:
        """Speak using local Piper TTS.

        SECURITY: Uses subprocess pipes instead of shell=True to prevent injection.
        """
        try:
            # Find piper binary - check venv first, then system PATH
            script_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            piper_bin = os.path.join(script_dir, "venv", "bin", "piper")
            if not os.path.exists(piper_bin):
                # Fallback to system piper
                piper_bin = "piper"

            # SECURITY: Use subprocess pipes instead of shell=True
            # This prevents command injection via $(cmd), `cmd`, ; cmd, etc.
            piper_proc = subprocess.Popen(
                [piper_bin, "--model", self.local_voice, "--length-scale", "0.7", "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            aplay_proc = subprocess.Popen(
                ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-q"],
                stdin=piper_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Send text directly to piper's stdin (no shell escaping needed)
            piper_proc.stdin.write(text.encode("utf-8"))
            piper_proc.stdin.close()

            # Wait for both processes to complete
            piper_proc.stdout.close()
            aplay_proc.wait()
            piper_proc.wait()

            return True

        except FileNotFoundError as e:
            logger.error("Piper TTS error: piper or aplay not found - %s", e)
            return False
        except Exception as e:
            logger.error("Piper TTS error: %s", e)
            return False

    def _speak_google_chunk(self, text: str) -> bool:
        """Speak a single chunk using Google Cloud TTS."""
        from google.cloud import texttospeech

        try:
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.language_code,
                name=self.voice_name,
            )

            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=self.speed,
            )

            synthesis_input = texttospeech.SynthesisInput(text=text)

            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

            # Save to temp file and play with mpv
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(response.audio_content)
                temp_path = f.name

            subprocess.run(
                ["mpv", "--no-video", "--really-quiet", temp_path],
                check=True,
            )

            os.unlink(temp_path)
            return True

        except Exception as e:
            logger.error("Google TTS error: %s", e)
            return False

    def stop(self):
        """Stop any currently playing audio."""
        subprocess.run(["pkill", "-f", "mpv"], check=False)
        subprocess.run(["pkill", "-f", "aplay"], check=False)
