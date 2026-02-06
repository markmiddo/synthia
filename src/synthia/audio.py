"""Audio capture for Synthia."""

import logging
import queue
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd
from scipy import signal

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio from the microphone while a key is held."""

    def __init__(
        self, target_sample_rate: int = 16000, channels: int = 1, device: Optional[int] = None
    ):
        self.target_sample_rate = target_sample_rate  # What Google expects
        self.channels = channels
        self.device = device
        self.recording = False
        self.audio_queue = queue.Queue()
        self.stream = None

        # Find USB microphone if no device specified
        if self.device is None:
            self.device = self._find_usb_mic()

        # Get the device's native sample rate
        self.device_sample_rate = self._get_device_sample_rate()
        logger.debug(
            "Device sample rate: %sHz, target: %sHz",
            self.device_sample_rate,
            self.target_sample_rate,
        )

    def _find_usb_mic(self) -> Optional[int]:
        """Find a USB microphone device."""
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            name = device["name"].lower()
            if device["max_input_channels"] > 0:
                # Prefer USB microphone
                if "usb" in name and "microphone" in name:
                    logger.info("Found USB Microphone: %s (device %s)", device["name"], i)
                    return i
        # Fallback to pulse
        for i, device in enumerate(devices):
            if device["name"] == "pulse" and device["max_input_channels"] > 0:
                logger.info("Using PulseAudio: %s (device %s)", device["name"], i)
                return i
        return None

    def _get_device_sample_rate(self) -> int:
        """Get the native sample rate of the selected device."""
        if self.device is not None:
            device_info = sd.query_devices(self.device)
            return int(device_info["default_samplerate"])
        return 44100  # Default fallback

    def _resample(self, audio_data: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
        """Resample audio from one sample rate to another."""
        if orig_rate == target_rate:
            return audio_data

        # Calculate the number of samples in the resampled audio
        num_samples = int(len(audio_data) * target_rate / orig_rate)
        resampled = signal.resample(audio_data, num_samples)
        return resampled.astype(np.int16)

    def _audio_callback(self, indata, frames, time, status):
        """Callback for audio stream - adds audio chunks to queue."""
        if status:
            logger.debug("Audio status: %s", status)
        if self.recording:
            self.audio_queue.put(indata.copy())

    def start_recording(self):
        """Start recording audio."""
        self.recording = True
        # Clear any old audio from queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self.device_sample_rate,  # Use device's native rate
            channels=self.channels,
            dtype=np.int16,
            callback=self._audio_callback,
        )
        self.stream.start()
        logger.info("Recording...")

    def stop_recording(self) -> bytes:
        """Stop recording and return the audio data as bytes (resampled to target rate)."""
        self.recording = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Collect all audio chunks
        chunks = []
        while not self.audio_queue.empty():
            try:
                chunks.append(self.audio_queue.get_nowait())
            except queue.Empty:
                break

        if not chunks:
            logger.warning("No audio recorded")
            return b""

        # Concatenate all chunks
        audio_data = np.concatenate(chunks, axis=0).flatten()
        duration = len(audio_data) / self.device_sample_rate
        logger.info("Stopped recording (%.1fs)", duration)

        # Check audio levels
        max_level = np.abs(audio_data).max()
        mean_level = np.abs(audio_data).mean()
        logger.debug("Audio levels - max: %s, mean: %.0f", max_level, mean_level)

        if max_level < 100:
            logger.warning("Audio levels very low - check microphone")

        # Resample to target rate for Google STT
        if self.device_sample_rate != self.target_sample_rate:
            logger.debug("Resampling %sHz -> %sHz", self.device_sample_rate, self.target_sample_rate)
            audio_data = self._resample(
                audio_data, self.device_sample_rate, self.target_sample_rate
            )

        return audio_data.tobytes()


def list_audio_devices():
    """List available audio input devices."""
    print("\nAvailable audio input devices:")
    print("-" * 40)
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device["max_input_channels"] > 0:
            default = " (default)" if i == sd.default.device[0] else ""
            print(f"  [{i}] {device['name']} @ {device['default_samplerate']}Hz{default}")
    print()
