"""Wake word detection for Synthia.

Uses a simple approach: continuously listen and check transcription for wake word.
For production, you'd want something like Porcupine or Snowboy for offline detection.
"""

import threading
import time
import numpy as np
import sounddevice as sd
from typing import Callable, Optional


class WakeWordDetector:
    """Detects wake word using continuous audio monitoring.

    This is a simple implementation that periodically samples audio
    and checks for the wake word. For lower latency and better accuracy,
    consider using Picovoice Porcupine or similar.
    """

    def __init__(
        self,
        wake_words: list[str] = ["hey linux", "hey voice", "ok linux"],
        on_wake: Optional[Callable] = None,
        sample_rate: int = 16000,
        chunk_duration: float = 2.0,  # seconds
        device: Optional[int] = None,
    ):
        self.wake_words = [w.lower() for w in wake_words]
        self.on_wake = on_wake
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.device = device

        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._transcriber = None

    def set_transcriber(self, transcriber):
        """Set the transcriber to use for wake word detection."""
        self._transcriber = transcriber

    def _listen_loop(self):
        """Main listening loop - runs in background thread."""
        print("👂 Wake word detection active...")

        while self.running:
            try:
                # Record a short chunk
                frames = int(self.sample_rate * self.chunk_duration)
                audio = sd.rec(
                    frames,
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype=np.int16,
                    device=self.device
                )
                sd.wait()

                # Check if audio has enough energy (not silence)
                if np.abs(audio).mean() < 100:
                    continue

                # Transcribe and check for wake word
                if self._transcriber:
                    text = self._transcriber.transcribe(audio.tobytes())
                    text_lower = text.lower()

                    for wake_word in self.wake_words:
                        if wake_word in text_lower:
                            print(f"🎤 Wake word detected: '{wake_word}'")
                            if self.on_wake:
                                self.on_wake()
                            # Brief pause after detection
                            time.sleep(0.5)
                            break

            except Exception as e:
                print(f"Wake word error: {e}")
                time.sleep(1)

    def start(self):
        """Start wake word detection in background."""
        if self.running:
            return

        self.running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop wake word detection."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        print("👂 Wake word detection stopped")
