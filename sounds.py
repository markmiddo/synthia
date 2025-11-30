"""Sound effects for LinuxVoice."""

import subprocess
import os
import tempfile
import base64

# Simple beep sounds encoded as base64 WAV
# These are tiny sine wave beeps generated programmatically

def _generate_beep(frequency: int, duration_ms: int, volume: float = 0.5) -> bytes:
    """Generate a simple beep as WAV bytes."""
    import struct
    import math

    sample_rate = 44100
    num_samples = int(sample_rate * duration_ms / 1000)

    # Generate sine wave
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        # Apply envelope to avoid clicks
        envelope = min(1.0, min(i, num_samples - i) / (sample_rate * 0.01))
        value = int(32767 * volume * envelope * math.sin(2 * math.pi * frequency * t))
        samples.append(struct.pack('<h', value))

    audio_data = b''.join(samples)

    # Create WAV header
    wav_header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + len(audio_data),
        b'WAVE',
        b'fmt ',
        16,  # PCM header size
        1,   # PCM format
        1,   # Mono
        sample_rate,
        sample_rate * 2,  # Byte rate
        2,   # Block align
        16,  # Bits per sample
        b'data',
        len(audio_data)
    )

    return wav_header + audio_data


class SoundEffects:
    """Play sound effects for LinuxVoice events."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._temp_files = []

        # Pre-generate sounds
        self._start_sound = _generate_beep(880, 100, 0.3)   # High beep
        self._stop_sound = _generate_beep(440, 100, 0.3)    # Low beep
        self._error_sound = _generate_beep(220, 200, 0.3)   # Very low beep

    def _play_wav(self, wav_data: bytes):
        """Play WAV data using paplay."""
        if not self.enabled:
            return

        try:
            # Write to temp file and play
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                f.write(wav_data)
                temp_path = f.name

            subprocess.Popen(
                ['paplay', temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Clean up after a delay (let it play first)
            self._temp_files.append(temp_path)
            if len(self._temp_files) > 10:
                old_file = self._temp_files.pop(0)
                try:
                    os.unlink(old_file)
                except:
                    pass

        except Exception as e:
            print(f"Sound error: {e}")

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
            except:
                pass
        self._temp_files = []
