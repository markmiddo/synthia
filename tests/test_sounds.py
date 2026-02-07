"""Tests for synthia.sounds module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from synthia.sounds import (
    BEEP_SAMPLE_RATE,
    BEEP_VOLUME,
    DURATION_LONG,
    DURATION_SHORT,
    FREQ_ERROR,
    FREQ_HIGH,
    FREQ_LOW,
    MAX_TEMP_FILES,
    SoundEffects,
    _generate_beep,
)


class TestGenerateBeep:
    """Tests for the _generate_beep function."""

    def test_produces_valid_wav_bytes(self):
        """WAV output must start with the RIFF header."""
        result = _generate_beep(440, 100)
        assert isinstance(result, bytes)
        assert result[:4] == b"RIFF"

    def test_wav_contains_wave_marker(self):
        """WAV output must contain the WAVE format marker after RIFF."""
        result = _generate_beep(440, 100)
        assert result[8:12] == b"WAVE"

    def test_wav_contains_fmt_chunk(self):
        """WAV output must contain the fmt chunk."""
        result = _generate_beep(440, 100)
        assert b"fmt " in result

    def test_wav_contains_data_chunk(self):
        """WAV output must contain the data chunk."""
        result = _generate_beep(440, 100)
        assert b"data" in result

    def test_different_frequencies_produce_different_output(self):
        """Different frequencies should generate distinct audio data."""
        beep_low = _generate_beep(220, 100)
        beep_high = _generate_beep(880, 100)
        assert beep_low != beep_high

    def test_same_frequency_produces_same_output(self):
        """Identical parameters should produce identical output (deterministic)."""
        beep_a = _generate_beep(440, 100, 0.5)
        beep_b = _generate_beep(440, 100, 0.5)
        assert beep_a == beep_b

    def test_different_durations_produce_different_lengths(self):
        """Longer duration should produce more audio data (larger output)."""
        short = _generate_beep(440, 50)
        long = _generate_beep(440, 200)
        assert len(long) > len(short)

    def test_default_volume(self):
        """Default volume parameter should be 0.5."""
        # Calling without volume should match calling with 0.5 explicitly
        default_result = _generate_beep(440, 100)
        explicit_result = _generate_beep(440, 100, 0.5)
        assert default_result == explicit_result

    def test_different_volumes_produce_different_output(self):
        """Different volume levels should produce different sample data."""
        quiet = _generate_beep(440, 100, 0.1)
        loud = _generate_beep(440, 100, 0.9)
        assert quiet != loud


class TestSoundEffectsInit:
    """Tests for SoundEffects.__init__."""

    @patch("synthia.sounds.atexit.register")
    def test_init_registers_atexit_cleanup(self, mock_register):
        """__init__ should register the cleanup method with atexit."""
        effects = SoundEffects(enabled=False)
        mock_register.assert_called_once_with(effects.cleanup)

    @patch("synthia.sounds.atexit.register")
    def test_init_creates_temp_files_list(self, mock_register):
        """__init__ should initialize an empty _temp_files list."""
        effects = SoundEffects(enabled=False)
        assert effects._temp_files == []

    @patch("synthia.sounds.atexit.register")
    def test_init_stores_enabled_flag(self, mock_register):
        """__init__ should store the enabled parameter."""
        effects_on = SoundEffects(enabled=True)
        effects_off = SoundEffects(enabled=False)
        assert effects_on.enabled is True
        assert effects_off.enabled is False

    @patch("synthia.sounds.atexit.register")
    def test_init_pregenerates_sounds(self, mock_register):
        """__init__ should pre-generate all three sound effects."""
        effects = SoundEffects(enabled=False)
        assert isinstance(effects._start_sound, bytes)
        assert isinstance(effects._stop_sound, bytes)
        assert isinstance(effects._error_sound, bytes)
        # All should be valid WAV
        assert effects._start_sound[:4] == b"RIFF"
        assert effects._stop_sound[:4] == b"RIFF"
        assert effects._error_sound[:4] == b"RIFF"

    @patch("synthia.sounds.atexit.register")
    def test_init_default_enabled(self, mock_register):
        """Default enabled parameter should be True."""
        effects = SoundEffects()
        assert effects.enabled is True


class TestSoundEffectsCleanup:
    """Tests for SoundEffects.cleanup."""

    @patch("synthia.sounds.atexit.register")
    def test_cleanup_removes_temp_files(self, mock_register, tmp_path):
        """cleanup should remove all tracked temp files."""
        effects = SoundEffects(enabled=False)

        # Create real temp files to clean up
        temp_files = []
        for i in range(3):
            f = tmp_path / f"test_{i}.wav"
            f.write_bytes(b"fake wav data")
            temp_files.append(str(f))

        effects._temp_files = temp_files

        effects.cleanup()

        for f in temp_files:
            assert not os.path.exists(f)

    @patch("synthia.sounds.atexit.register")
    def test_cleanup_resets_temp_files_list(self, mock_register, tmp_path):
        """cleanup should reset _temp_files to an empty list."""
        effects = SoundEffects(enabled=False)

        f = tmp_path / "test.wav"
        f.write_bytes(b"fake wav data")
        effects._temp_files = [str(f)]

        effects.cleanup()

        assert effects._temp_files == []

    @patch("synthia.sounds.atexit.register")
    def test_cleanup_handles_missing_files_gracefully(self, mock_register):
        """cleanup should not raise if temp files are already gone."""
        effects = SoundEffects(enabled=False)
        effects._temp_files = ["/nonexistent/file.wav"]

        # Should not raise
        effects.cleanup()
        assert effects._temp_files == []

    @patch("synthia.sounds.atexit.register")
    def test_cleanup_with_no_temp_files(self, mock_register):
        """cleanup should work fine when there are no temp files."""
        effects = SoundEffects(enabled=False)
        assert effects._temp_files == []

        # Should not raise
        effects.cleanup()
        assert effects._temp_files == []


class TestSoundEffectsPlayback:
    """Tests for SoundEffects play methods."""

    @patch("synthia.sounds.atexit.register")
    @patch("synthia.sounds.subprocess.Popen")
    def test_play_start_writes_and_plays(self, mock_popen, mock_register, tmp_path):
        """play_start should write a temp WAV file and call paplay."""
        effects = SoundEffects(enabled=True)
        effects.play_start()

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert call_args[0][0][0] == "paplay"

    @patch("synthia.sounds.atexit.register")
    @patch("synthia.sounds.subprocess.Popen")
    def test_play_does_nothing_when_disabled(self, mock_popen, mock_register):
        """Play methods should do nothing when enabled is False."""
        effects = SoundEffects(enabled=False)
        effects.play_start()
        effects.play_stop()
        effects.play_error()

        mock_popen.assert_not_called()

    @patch("synthia.sounds.atexit.register")
    @patch("synthia.sounds.subprocess.Popen")
    def test_play_tracks_temp_files(self, mock_popen, mock_register):
        """Playing a sound should track the temp file for later cleanup."""
        effects = SoundEffects(enabled=True)
        effects.play_start()

        assert len(effects._temp_files) == 1
        assert effects._temp_files[0].endswith(".wav")

    @patch("synthia.sounds.atexit.register")
    @patch("synthia.sounds.subprocess.Popen")
    def test_play_cleans_old_files_when_exceeding_max(self, mock_popen, mock_register, tmp_path):
        """When temp files exceed MAX_TEMP_FILES, oldest should be removed."""
        effects = SoundEffects(enabled=True)

        # Pre-populate with MAX_TEMP_FILES existing entries
        existing_files = []
        for i in range(MAX_TEMP_FILES):
            f = tmp_path / f"old_{i}.wav"
            f.write_bytes(b"fake")
            existing_files.append(str(f))

        effects._temp_files = list(existing_files)

        # Play one more to trigger cleanup of the oldest
        effects.play_start()

        # The first old file should have been removed
        assert not os.path.exists(existing_files[0])
        # List should still be MAX_TEMP_FILES long (removed 1 old, added 1 new)
        assert len(effects._temp_files) == MAX_TEMP_FILES
