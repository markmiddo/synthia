"""Text-to-Speech integration with Google Cloud and local Piper options."""

import os
import subprocess
import tempfile


class TextToSpeech:
    """Converts text to speech using Google Cloud TTS or local Piper."""

    def __init__(self, credentials_path: str = None, voice_name: str = "en-US-Neural2-J",
                 speed: float = 1.0, use_local: bool = False,
                 local_voice: str = "~/.local/share/piper-voices/en_US-amy-medium.onnx"):
        self.use_local = use_local
        self.speed = speed
        self.voice_name = voice_name
        self.local_voice = os.path.expanduser(local_voice)
        self.client = None

        if use_local:
            print(f"Piper TTS initialized with voice: {os.path.basename(self.local_voice)}")
        else:
            self._init_google(credentials_path, voice_name)

    def _init_google(self, credentials_path: str, voice_name: str):
        """Initialize Google Cloud TTS."""
        from google.cloud import texttospeech

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        self.client = texttospeech.TextToSpeechClient()
        self.voice_name = voice_name
        self.language_code = "-".join(voice_name.split("-")[:2])
        print(f"Google TTS initialized with voice: {voice_name}")

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
            print(f"Speaking: {text[:50]}{'...' if len(text) > 50 else ''}")

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
            print(f"TTS error: {e}")
            return False

    def _speak_piper(self, text: str) -> bool:
        """Speak using local Piper TTS."""
        try:
            # Remove quotes instead of escaping to avoid backslash issues
            safe_text = text.replace('"', '').replace("'", "")

            # Use full path to piper in venv
            piper_bin = "/home/markmiddo/Misc/linuxvoice/venv/bin/piper"
            cmd = f'echo "{safe_text}" | {piper_bin} --model "{self.local_voice}" --output-raw | aplay -r 22050 -f S16_LE -t raw -q'

            subprocess.run(cmd, shell=True, check=True)
            return True

        except Exception as e:
            print(f"Piper TTS error: {e}")
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
            print(f"Google TTS error: {e}")
            return False

    def stop(self):
        """Stop any currently playing audio."""
        subprocess.run(["pkill", "-f", "mpv"], check=False)
        subprocess.run(["pkill", "-f", "aplay"], check=False)
