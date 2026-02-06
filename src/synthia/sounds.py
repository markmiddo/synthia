"""Sound effects for Synthia."""

import atexit
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Audio constants
BEEP_SAMPLE_RATE = 44100
BEEP_VOLUME = 0.3
MAX_TEMP_FILES = 10

# Beep frequencies (Hz)
FREQ_HIGH = 880    # Recording start
FREQ_LOW = 440     # Recording stop
FREQ_ERROR = 220   # Error notification

# Beep durations (ms)
DURATION_SHORT = 100
DURATION_LONG = 200


def _generate_beep(frequency: int, duration_ms: int, volume: float = 0.5) -> bytes:
    """Generate a simple beep as WAV bytes."""
    import math
    import struct

    sample_rate = BEEP_SAMPLE_RATE
    num_samples = int(sample_rate * duration_ms / 1000)

    # Generate sine wave
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        # Apply envelope to avoid clicks
        envelope = min(1.0, min(i, num_samples - i) / (sample_rate * 0.01))
        value = int(32767 * volume * envelope * math.sin(2 * math.pi * frequency * t))
        samples.append(struct.pack("<h", value))

    audio_data = b"".join(samples)

    # Create WAV header
    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(audio_data),
        b"WAVE",
        b"fmt ",
        16,  # PCM header size
        1,  # PCM format
        1,  # Mono
        sample_rate,
        sample_rate * 2,  # Byte rate
        2,  # Block align
        16,  # Bits per sample
        b"data",
        len(audio_data),
    )

    return wav_header + audio_data


class SoundEffects:
    """Play sound effects for Synthia events."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._temp_files = []
        atexit.register(self.cleanup)

        # Pre-generate sounds
        self._start_sound = _generate_beep(FREQ_HIGH, DURATION_SHORT, BEEP_VOLUME)
        self._stop_sound = _generate_beep(FREQ_LOW, DURATION_SHORT, BEEP_VOLUME)
        self._error_sound = _generate_beep(FREQ_ERROR, DURATION_LONG, BEEP_VOLUME)

    def _play_wav(self, wav_data: bytes):
        """Play WAV data using paplay."""
        if not self.enabled:
            return

        try:
            # Write to temp file and play
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_data)
                temp_path = f.name

            subprocess.Popen(
                ["paplay", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            # Clean up after a delay (let it play first)
            self._temp_files.append(temp_path)
            if len(self._temp_files) > MAX_TEMP_FILES:
                old_file = self._temp_files.pop(0)
                try:
                    os.unlink(old_file)
                except OSError as e:
                    logger.debug("Failed to cleanup temp file %s: %s", old_file, e)

        except Exception as e:
            logger.error("Sound error: %s", e)

    def play_start(self):
        """Play recording start sound."""
        self._play_wav(self._start_sound)

    def play_stop(self):
        """Play recording stop sound."""
        self._play_wav(self._stop_sound)

    def play_error(self):
        """Play error sound."""
        self._play_wav(self._error_sound)

    def cleanup(self):
        """Clean up temp files."""
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError as e:
                logger.debug("Failed to cleanup temp file %s: %s", f, e)
        self._temp_files = []
