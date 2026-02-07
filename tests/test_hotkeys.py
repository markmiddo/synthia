"""Tests for synthia.hotkeys module."""

from unittest.mock import MagicMock

import pytest

from synthia.hotkeys import (
    EvdevHotkeyListener,
    HotkeyListener,
    PynputHotkeyListener,
    create_hotkey_listener,
)


# -- Helpers ------------------------------------------------------------------


def _make_callbacks():
    """Create a dict of four mock callbacks for hotkey listeners."""
    return {
        "on_dictation_press": MagicMock(),
        "on_dictation_release": MagicMock(),
        "on_assistant_press": MagicMock(),
        "on_assistant_release": MagicMock(),
    }


# -- KEY_CODE_MAP -------------------------------------------------------------


class TestKeyCodeMap:
    """Tests for EvdevHotkeyListener.KEY_CODE_MAP."""

    def test_contains_right_ctrl(self):
        """KEY_CODE_MAP maps Key.ctrl_r to evdev code 97."""
        assert EvdevHotkeyListener.KEY_CODE_MAP["Key.ctrl_r"] == 97

    def test_contains_left_ctrl(self):
        """KEY_CODE_MAP maps Key.ctrl_l to evdev code 29."""
        assert EvdevHotkeyListener.KEY_CODE_MAP["Key.ctrl_l"] == 29

    def test_contains_right_alt(self):
        """KEY_CODE_MAP maps Key.alt_r to evdev code 100."""
        assert EvdevHotkeyListener.KEY_CODE_MAP["Key.alt_r"] == 100

    def test_contains_left_alt(self):
        """KEY_CODE_MAP maps Key.alt_l to evdev code 56."""
        assert EvdevHotkeyListener.KEY_CODE_MAP["Key.alt_l"] == 56

    def test_contains_right_shift(self):
        """KEY_CODE_MAP maps Key.shift_r to evdev code 54."""
        assert EvdevHotkeyListener.KEY_CODE_MAP["Key.shift_r"] == 54

    def test_contains_left_shift(self):
        """KEY_CODE_MAP maps Key.shift_l to evdev code 42."""
        assert EvdevHotkeyListener.KEY_CODE_MAP["Key.shift_l"] == 42

    def test_has_six_entries(self):
        """KEY_CODE_MAP contains exactly six key mappings."""
        assert len(EvdevHotkeyListener.KEY_CODE_MAP) == 6


# -- EvdevHotkeyListener.get_key_code ----------------------------------------


class TestEvdevGetKeyCode:
    """Tests for EvdevHotkeyListener.get_key_code class method."""

    def test_known_key_returns_mapped_code(self):
        """get_key_code returns the evdev code for a known key string."""
        assert EvdevHotkeyListener.get_key_code("Key.ctrl_r") == 97
        assert EvdevHotkeyListener.get_key_code("Key.alt_r") == 100
        assert EvdevHotkeyListener.get_key_code("Key.shift_l") == 42

    def test_unknown_key_defaults_to_right_ctrl(self):
        """get_key_code defaults to 97 (Right Ctrl) for unknown key strings."""
        assert EvdevHotkeyListener.get_key_code("Key.unknown") == 97
        assert EvdevHotkeyListener.get_key_code("not_a_key") == 97
        assert EvdevHotkeyListener.get_key_code("") == 97


# -- EvdevHotkeyListener construction & interface ----------------------------


class TestEvdevHotkeyListener:
    """Tests for EvdevHotkeyListener behaviour without hardware."""

    def test_is_subclass_of_hotkey_listener(self):
        """EvdevHotkeyListener inherits from HotkeyListener."""
        assert issubclass(EvdevHotkeyListener, HotkeyListener)

    def test_has_start_stop_join_update_keys_methods(self):
        """EvdevHotkeyListener exposes the full HotkeyListener interface."""
        for method_name in ("start", "stop", "join", "update_keys"):
            assert hasattr(EvdevHotkeyListener, method_name)
            assert callable(getattr(EvdevHotkeyListener, method_name))

    def test_default_key_codes(self):
        """Constructor defaults to Right Ctrl (97) and Right Alt (100)."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)

        assert listener.dictation_key_code == 97
        assert listener.assistant_key_code == 100

    def test_custom_key_codes(self):
        """Constructor accepts custom key codes."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs, dictation_key_code=29, assistant_key_code=56)

        assert listener.dictation_key_code == 29
        assert listener.assistant_key_code == 56

    def test_initial_state_not_running(self):
        """Listener starts in the not-running state."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)

        assert listener.running is False
        assert listener.thread is None
        assert listener.devices == []

    def test_stop_sets_running_false(self):
        """stop() clears the running flag even if start() was never called."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)
        listener.running = True

        listener.stop()

        assert listener.running is False

    def test_join_noop_when_no_thread(self):
        """join() is safe to call when no thread exists."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)

        listener.join()  # Should not raise

    def test_update_keys_changes_codes(self):
        """update_keys converts key strings and updates both key codes."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)

        listener.update_keys("Key.shift_l", "Key.alt_l")

        assert listener.dictation_key_code == 42   # KEY_LEFTSHIFT
        assert listener.assistant_key_code == 56    # KEY_LEFTALT

    def test_update_keys_unknown_string_defaults(self):
        """update_keys falls back to 97 for unrecognised key strings."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)

        listener.update_keys("Key.bogus", "Key.nope")

        assert listener.dictation_key_code == 97
        assert listener.assistant_key_code == 97

    def test_start_raises_when_no_devices_found(self, monkeypatch):
        """start() raises RuntimeError when no keyboard devices are available."""
        cbs = _make_callbacks()
        listener = EvdevHotkeyListener(**cbs)

        # Simulate _find_keyboard_devices finding nothing
        monkeypatch.setattr(listener, "_find_keyboard_devices", lambda: [])

        with pytest.raises(RuntimeError, match="No keyboard devices found"):
            listener.start()


# -- PynputHotkeyListener construction & interface ---------------------------


class TestPynputHotkeyListener:
    """Tests for PynputHotkeyListener behaviour without hardware."""

    def test_is_subclass_of_hotkey_listener(self):
        """PynputHotkeyListener inherits from HotkeyListener."""
        assert issubclass(PynputHotkeyListener, HotkeyListener)

    def test_has_start_stop_join_update_keys_methods(self):
        """PynputHotkeyListener exposes the full HotkeyListener interface."""
        for method_name in ("start", "stop", "join", "update_keys"):
            assert hasattr(PynputHotkeyListener, method_name)
            assert callable(getattr(PynputHotkeyListener, method_name))

    def test_stores_callbacks_and_keys(self):
        """Constructor stores all callbacks and key objects."""
        cbs = _make_callbacks()
        sentinel_dictation = object()
        sentinel_assistant = object()

        listener = PynputHotkeyListener(
            **cbs,
            dictation_key=sentinel_dictation,
            assistant_key=sentinel_assistant,
        )

        assert listener.on_dictation_press is cbs["on_dictation_press"]
        assert listener.on_dictation_release is cbs["on_dictation_release"]
        assert listener.on_assistant_press is cbs["on_assistant_press"]
        assert listener.on_assistant_release is cbs["on_assistant_release"]
        assert listener.dictation_key is sentinel_dictation
        assert listener.assistant_key is sentinel_assistant

    def test_initial_state(self):
        """Listener starts with no active keys and no underlying listener."""
        cbs = _make_callbacks()
        listener = PynputHotkeyListener(**cbs, dictation_key=None, assistant_key=None)

        assert listener.listener is None
        assert listener.dictation_active is False
        assert listener.assistant_active is False

    def test_stop_noop_when_no_listener(self):
        """stop() is safe to call before start()."""
        cbs = _make_callbacks()
        listener = PynputHotkeyListener(**cbs, dictation_key=None, assistant_key=None)

        listener.stop()  # Should not raise

    def test_join_noop_when_no_listener(self):
        """join() is safe to call before start()."""
        cbs = _make_callbacks()
        listener = PynputHotkeyListener(**cbs, dictation_key=None, assistant_key=None)

        listener.join()  # Should not raise

    def test_on_press_fires_dictation_callback(self):
        """_on_press triggers dictation callback when dictation key is pressed."""
        cbs = _make_callbacks()
        sentinel_key = object()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=sentinel_key, assistant_key=object()
        )

        listener._on_press(sentinel_key)

        cbs["on_dictation_press"].assert_called_once()
        assert listener.dictation_active is True

    def test_on_press_fires_assistant_callback(self):
        """_on_press triggers assistant callback when assistant key is pressed."""
        cbs = _make_callbacks()
        sentinel_key = object()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=object(), assistant_key=sentinel_key
        )

        listener._on_press(sentinel_key)

        cbs["on_assistant_press"].assert_called_once()
        assert listener.assistant_active is True

    def test_on_press_ignores_unknown_key(self):
        """_on_press does nothing for an unrecognised key."""
        cbs = _make_callbacks()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=object(), assistant_key=object()
        )

        listener._on_press(object())

        cbs["on_dictation_press"].assert_not_called()
        cbs["on_assistant_press"].assert_not_called()

    def test_on_press_blocks_simultaneous_keys(self):
        """Only one hotkey can be active at a time (dictation blocks assistant)."""
        cbs = _make_callbacks()
        dictation_key = object()
        assistant_key = object()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=dictation_key, assistant_key=assistant_key
        )

        listener._on_press(dictation_key)
        listener._on_press(assistant_key)

        cbs["on_dictation_press"].assert_called_once()
        cbs["on_assistant_press"].assert_not_called()

    def test_on_release_fires_dictation_callback(self):
        """_on_release triggers dictation release callback after press."""
        cbs = _make_callbacks()
        sentinel_key = object()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=sentinel_key, assistant_key=object()
        )

        listener._on_press(sentinel_key)
        listener._on_release(sentinel_key)

        cbs["on_dictation_release"].assert_called_once()
        assert listener.dictation_active is False

    def test_on_release_fires_assistant_callback(self):
        """_on_release triggers assistant release callback after press."""
        cbs = _make_callbacks()
        sentinel_key = object()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=object(), assistant_key=sentinel_key
        )

        listener._on_press(sentinel_key)
        listener._on_release(sentinel_key)

        cbs["on_assistant_release"].assert_called_once()
        assert listener.assistant_active is False

    def test_on_release_ignored_without_prior_press(self):
        """_on_release is a no-op when the key was never pressed."""
        cbs = _make_callbacks()
        sentinel_key = object()
        listener = PynputHotkeyListener(
            **cbs, dictation_key=sentinel_key, assistant_key=object()
        )

        listener._on_release(sentinel_key)

        cbs["on_dictation_release"].assert_not_called()


# -- create_hotkey_listener factory ------------------------------------------


class TestCreateHotkeyListener:
    """Tests for the create_hotkey_listener factory function."""

    def test_returns_evdev_listener_on_wayland(self, clean_env, monkeypatch):
        """Factory returns EvdevHotkeyListener when Wayland is detected."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        cbs = _make_callbacks()

        listener = create_hotkey_listener(**cbs)

        assert isinstance(listener, EvdevHotkeyListener)

    def test_returns_pynput_listener_on_x11(self, clean_env, monkeypatch):
        """Factory returns PynputHotkeyListener when X11 is detected."""
        monkeypatch.setenv("DISPLAY", ":0")
        cbs = _make_callbacks()

        listener = create_hotkey_listener(
            **cbs, dictation_key="mock_key", assistant_key="mock_key"
        )

        assert isinstance(listener, PynputHotkeyListener)

    def test_returns_pynput_when_no_display(self, clean_env):
        """Factory falls back to PynputHotkeyListener when no display is set."""
        cbs = _make_callbacks()

        listener = create_hotkey_listener(
            **cbs, dictation_key=None, assistant_key=None
        )

        assert isinstance(listener, PynputHotkeyListener)

    def test_evdev_listener_receives_correct_key_codes(self, clean_env, monkeypatch):
        """Factory converts key strings to evdev codes for EvdevHotkeyListener."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        cbs = _make_callbacks()

        listener = create_hotkey_listener(
            **cbs,
            dictation_key_string="Key.shift_l",
            assistant_key_string="Key.alt_l",
        )

        assert isinstance(listener, EvdevHotkeyListener)
        assert listener.dictation_key_code == 42   # KEY_LEFTSHIFT
        assert listener.assistant_key_code == 56    # KEY_LEFTALT

    def test_evdev_listener_uses_default_key_strings(self, clean_env, monkeypatch):
        """Factory defaults to Key.ctrl_r / Key.alt_r when no strings given."""
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        cbs = _make_callbacks()

        listener = create_hotkey_listener(**cbs)

        assert isinstance(listener, EvdevHotkeyListener)
        assert listener.dictation_key_code == 97   # KEY_RIGHTCTRL
        assert listener.assistant_key_code == 100   # KEY_RIGHTALT

    def test_pynput_listener_receives_key_objects(self, clean_env, monkeypatch):
        """Factory passes key objects through to PynputHotkeyListener."""
        monkeypatch.setenv("DISPLAY", ":0")
        cbs = _make_callbacks()
        sentinel_dictation = object()
        sentinel_assistant = object()

        listener = create_hotkey_listener(
            **cbs,
            dictation_key=sentinel_dictation,
            assistant_key=sentinel_assistant,
        )

        assert isinstance(listener, PynputHotkeyListener)
        assert listener.dictation_key is sentinel_dictation
        assert listener.assistant_key is sentinel_assistant

    def test_result_is_always_a_hotkey_listener(self, clean_env, monkeypatch):
        """Factory always returns an instance of the HotkeyListener ABC."""
        cbs = _make_callbacks()

        # Wayland path
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        wayland_listener = create_hotkey_listener(**cbs)
        assert isinstance(wayland_listener, HotkeyListener)

        # X11 path
        monkeypatch.delenv("WAYLAND_DISPLAY")
        monkeypatch.setenv("DISPLAY", ":0")
        x11_listener = create_hotkey_listener(
            **cbs, dictation_key=None, assistant_key=None
        )
        assert isinstance(x11_listener, HotkeyListener)
