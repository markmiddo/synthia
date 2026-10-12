"""Text-to-Speech integration with Google Cloud and local Piper options."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from google.cloud import texttospeech

logger = logging.getLogger(__name__)

# Cross-process lock so two agents finishing simultaneously do not talk over
# each other. The second speak() call blocks until the first releases.
SPEECH_LOCK_PATH = "/tmp/synthia-tts.lock"
SPEECH_LOCK_TIMEOUT_S = 60.0


def _runtime_state_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "synthia", "runtime.json")


def is_voice_muted() -> bool:
    try:
        with open(_runtime_state_path(), encoding="utf-8") as f:
            return bool(json.load(f).get("tts_muted", False))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


@contextlib.contextmanager
def speech_lock(timeout: float = SPEECH_LOCK_TIMEOUT_S):
    """Serialize TTS playback across processes using flock.

    Yields True if the lock was acquired, False if timed out (caller should
    skip speaking to avoid pile-ups).
    """
    fd = os.open(SPEECH_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    logger.warning("TTS lock timed out after %.0fs; skipping", timeout)
                    break
                time.sleep(0.1)
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


# Maximum characters per TTS chunk for streaming effect
MAX_CHUNK_CHARS = 200
# Piper TTS native output sample rate
PIPER_SAMPLE_RATE = 22050


class TextToSpeech:
    """Converts text to speech using Google Cloud TTS or local Piper."""

    def __init__(
        self,
        credentials_path: str | None = None,
        voice_name: str = "en-US-Neural2-J",
        speed: float = 1.0,
        use_local: bool = False,
        local_voice: str = "~/.local/share/piper-voices/en_US-amy-medium.onnx",
    ) -> None:
        self.use_local = use_local
        self.speed = speed
        self.voice_name = voice_name
        self.local_voice = os.path.expanduser(local_voice)
        self.client: texttospeech.TextToSpeechClient | None = None
        # Processes currently speaking. cancel() bumps a generation; every speak() call
        # snapshots it on entry, so a cancel that lands while the call is still waiting for
        # the speech lock, synthesising, or between chunks is never lost (and never wiped
        # by a later call starting).
        self._playback: subprocess.Popen[bytes] | None = None
        self._synth: subprocess.Popen[bytes] | None = None
        self._gen = 0
        # Called when audio actually starts playing (for latency logging).
        self.on_play_start: Callable[[], None] | None = None
        self._gen_lock = threading.Lock()

        if use_local:
            logger.info("Piper TTS initialized with voice: %s", os.path.basename(self.local_voice))
        else:
            self._init_google(credentials_path, voice_name)

    def _init_google(self, credentials_path: str | None, voice_name: str) -> None:
        """Initialize Google Cloud TTS."""
        from google.cloud import texttospeech

        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        self.client = texttospeech.TextToSpeechClient()
        self.voice_name = voice_name
        self.language_code = "-".join(voice_name.split("-")[:2])
        logger.info("Google TTS initialized with voice: %s", voice_name)

    def _split_into_chunks(self, text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
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

    def speak(self, text: str, ignore_mute: bool = False) -> bool:
        """Convert text to speech and play it.

        Serialized across processes via speech_lock so concurrent agents
        never overlap. The runtime mute silences background speech (agents);
        a reply to something Mark just asked passes ignore_mute=True.
        """
        if not text:
            return False

        gen = self._gen
        if not ignore_mute and is_voice_muted():
            logger.debug("TTS muted via runtime state; skipping speak")
            return False

        with speech_lock() as acquired:
            if not acquired:
                return False
            # Re-check mute after waiting in queue: user may have muted while
            # this call was blocked behind another speaker.
            if not ignore_mute and is_voice_muted():
                logger.debug("TTS muted while waiting for lock; skipping")
                return False
            try:
                logger.debug("Speaking: %s%s", text[:50], "..." if len(text) > 50 else "")

                if self._cancelled_since(gen):
                    return False

                if self.use_local:
                    return self._speak_piper(text, gen)

                # For Google TTS, use chunking for longer text
                if len(text) < 150:
                    return self._speak_google_chunk(text, gen)

                chunks = self._split_into_chunks(text)
                for chunk in chunks:
                    if self._cancelled_since(gen):
                        return False
                    if chunk.strip() and not self._speak_google_chunk(chunk, gen):
                        return False
                return True

            except Exception as e:
                logger.error("TTS error: %s", e)
                return False

    def _cancelled_since(self, gen: int) -> bool:
        return self._gen != gen

    def _speak_piper(self, text: str, gen: int) -> bool:
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

            if self._cancelled_since(gen):
                return False

            # SECURITY: Use subprocess pipes instead of shell=True
            # This prevents command injection via $(cmd), `cmd`, ; cmd, etc.
            piper_proc = subprocess.Popen(
                [piper_bin, "--model", self.local_voice, "--length-scale", "0.7", "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._synth = piper_proc
            if self._cancelled_since(gen):
                self._terminate(piper_proc)
                return False

            aplay_proc = subprocess.Popen(
                ["aplay", "-r", str(PIPER_SAMPLE_RATE), "-f", "S16_LE", "-t", "raw", "-q"],
                stdin=piper_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._playback = aplay_proc
            if self._cancelled_since(gen):
                self._terminate(aplay_proc)
                self._terminate(piper_proc)
                return False
            self._notify_play_start()

            # Send text directly to piper's stdin (no shell escaping needed)
            if piper_proc.stdin is not None:
                piper_proc.stdin.write(text.encode("utf-8"))
                piper_proc.stdin.close()

            # Wait for both processes to complete
            if piper_proc.stdout is not None:
                piper_proc.stdout.close()
            try:
                aplay_proc.wait()
                piper_proc.wait()
            finally:
                self._playback = None
                self._synth = None

            return not self._cancelled_since(gen)

        except FileNotFoundError as e:
            logger.error("Piper TTS error: piper or aplay not found - %s", e)
            return False
        except Exception as e:
            logger.error("Piper TTS error: %s", e)
            return False

    def _speak_google_chunk(self, text: str, gen: int) -> bool:
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

            assert self.client is not None
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

            if self._cancelled_since(gen):
                return False

            # Save to temp file and play with mpv
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(response.audio_content)
                temp_path = f.name

            try:
                return self._play_mp3(temp_path, gen)
            finally:
                os.unlink(temp_path)

        except Exception as e:
            logger.error("Google TTS error: %s", e)
            return False

    def _play_mp3(self, path: str, gen: int) -> bool:
        """Play an mp3 with mpv, cancellable like any other speech."""
        proc = subprocess.Popen(["mpv", "--no-video", "--really-quiet", path])
        self._playback = proc
        try:
            if self._cancelled_since(gen):
                self._terminate(proc)
            else:
                self._notify_play_start()
            if proc.wait() != 0 and not self._cancelled_since(gen):
                raise subprocess.CalledProcessError(proc.returncode, "mpv")
        finally:
            self._playback = None
        return not self._cancelled_since(gen)

    def _notify_play_start(self) -> None:
        cb = self.on_play_start
        if cb is not None:
            try:
                cb()
            except Exception:
                logger.exception("on_play_start failed")

    def synthesize_to_file(self, text: str, path: str) -> bool:
        """Render `text` with the configured Google voice into an mp3 at `path` (no playback)."""
        if self.use_local or self.client is None:
            return False
        from google.cloud import texttospeech

        try:
            response = self.client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=text),
                voice=texttospeech.VoiceSelectionParams(
                    language_code=self.language_code, name=self.voice_name
                ),
                audio_config=texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3,
                    speaking_rate=self.speed,
                ),
            )
            tmp = f"{path}.part"
            with open(tmp, "wb") as f:
                f.write(response.audio_content)
            os.replace(tmp, path)
            return True
        except Exception as e:
            logger.warning("could not render %r: %s", text, e)
            return False

    def play_file(self, path: str, ignore_mute: bool = False) -> bool:
        """Play a pre-rendered mp3 through the same lock and cancel path as speak()."""
        gen = self._gen
        if not ignore_mute and is_voice_muted():
            return False
        with speech_lock() as acquired:
            if not acquired or self._cancelled_since(gen):
                return False
            try:
                return self._play_mp3(path, gen)
            except Exception as e:
                logger.error("playing %s failed: %s", path, e)
                return False

    def cancel(self) -> None:
        """Stop only the playback this instance started (unlike stop(), which pkills mpv)."""
        with self._gen_lock:
            self._gen += 1
        for proc in (self._playback, self._synth):
            if proc is not None:
                self._terminate(proc)

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is None:
            proc.terminate()

    def stop(self) -> None:
        """Stop any currently playing audio."""
        subprocess.run(["pkill", "-f", "mpv"], check=False)
        subprocess.run(["pkill", "-f", "aplay"], check=False)
