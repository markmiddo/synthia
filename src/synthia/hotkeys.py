"""Hotkey handling for Synthia with Wayland and X11 support.

On Wayland: Uses evdev to read directly from input devices.
On X11: Uses pynput for global keyboard hooks.
"""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from .display import is_wayland

logger = logging.getLogger(__name__)


class HotkeyListener(ABC):
    """Abstract base class for hotkey listeners."""

    @abstractmethod
    def start(self) -> None:
        """Start listening for hotkeys."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop listening for hotkeys."""
        pass

    @abstractmethod
    def join(self) -> None:
        """Wait for listener to finish."""
        pass

    @abstractmethod
    def update_keys(self, dictation_key_string: str, assistant_key_string: str) -> None:
        """Update hotkeys without restarting the listener."""
        pass


class EvdevHotkeyListener(HotkeyListener):
    """Hotkey listener using evdev (works on Wayland).

    Requires user to be in 'input' group:
        sudo usermod -aG input $USER
        # Then logout/login
    """

    # Key code mappings from pynput format to evdev codes
    KEY_CODE_MAP = {
        "Key.ctrl_r": 97,   # KEY_RIGHTCTRL
        "Key.ctrl_l": 29,   # KEY_LEFTCTRL
        "Key.alt_r": 100,   # KEY_RIGHTALT
        "Key.alt_l": 56,    # KEY_LEFTALT
        "Key.shift_r": 54,  # KEY_RIGHTSHIFT
        "Key.shift_l": 42,  # KEY_LEFTSHIFT
    }

    def __init__(
        self,
        on_dictation_press: Callable[[], None],
        on_dictation_release: Callable[[], None],
        on_assistant_press: Callable[[], None],
        on_assistant_release: Callable[[], None],
        dictation_key_code: int = 97,  # Default: Right Ctrl
        assistant_key_code: int = 100,  # Default: Right Alt
    ) -> None:
        self.on_dictation_press = on_dictation_press
        self.on_dictation_release = on_dictation_release
        self.on_assistant_press = on_assistant_press
        self.on_assistant_release = on_assistant_release
        self.dictation_key_code = dictation_key_code
        self.assistant_key_code = assistant_key_code

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.devices: list = []

    @classmethod
    def get_key_code(cls, key_string: str) -> int:
        """Convert pynput key string to evdev key code."""
        return cls.KEY_CODE_MAP.get(key_string, 97)  # Default to Right Ctrl

    def _find_keyboard_devices(self) -> list:
        """Find all keyboard input devices."""
        try:
            from evdev import InputDevice, ecodes, list_devices

            keyboards = []
            for path in list_devices():
                try:
                    device = InputDevice(path)
                    capabilities = device.capabilities()

                    # Check if device has key events and has our target keys
                    if ecodes.EV_KEY in capabilities:
                        keys = capabilities[ecodes.EV_KEY]
                        if self.dictation_key_code in keys or self.assistant_key_code in keys:
                            keyboards.append(device)
                            logger.info("Found keyboard: %s (%s)", device.name, device.path)
                except (PermissionError, OSError) as e:
                    continue

            return keyboards
        except ImportError:
            logger.error("evdev not installed. Install with: pip install evdev")
            return []

    def _listen(self) -> None:
        """Main listening loop for evdev."""
        try:
            from selectors import EVENT_READ, DefaultSelector

            from evdev import ecodes

            selector = DefaultSelector()
            for device in self.devices:
                selector.register(device, EVENT_READ)

            while self.running:
                for key, mask in selector.select(timeout=0.1):
                    device = key.fileobj
                    try:
                        for event in device.read():
                            if event.type == ecodes.EV_KEY:
                                # Key press (1) or release (0)
                                if event.code == self.dictation_key_code:
                                    if event.value == 1:  # Press
                                        self.on_dictation_press()
                                    elif event.value == 0:  # Release
                                        self.on_dictation_release()
                                elif event.code == self.assistant_key_code:
                                    if event.value == 1:  # Press
                                        self.on_assistant_press()
                                    elif event.value == 0:  # Release
                                        self.on_assistant_release()
                    except BlockingIOError:
                        pass

            selector.close()
        except Exception as e:
            logger.error("evdev listener error: %s", e)

    def start(self) -> None:
        """Start the evdev listener in a background thread."""
        self.devices = self._find_keyboard_devices()
        if not self.devices:
            raise RuntimeError(
                "No keyboard devices found. Make sure you're in the 'input' group:\n"
                "  sudo usermod -aG input $USER\n"
                "Then logout and login again."
            )

        self.running = True
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the listener."""
        self.running = False
        for device in self.devices:
            try:
                device.close()
            except Exception as e:
                logger.debug("Failed to close device: %s", e)

    def join(self) -> None:
        """Wait for the listener thread to finish."""
        if self.thread:
            self.thread.join()

    def update_keys(self, dictation_key_string: str, assistant_key_string: str) -> None:
        """Update hotkeys without restarting the listener."""
        self.dictation_key_code = self.get_key_code(dictation_key_string)
        self.assistant_key_code = self.get_key_code(assistant_key_string)
        logger.info(
            "Hotkeys updated: dictation=%s (code %s), assistant=%s (code %s)",
            dictation_key_string,
            self.dictation_key_code,
            assistant_key_string,
            self.assistant_key_code,
        )


class PynputHotkeyListener(HotkeyListener):
    """Hotkey listener using pynput (works on X11)."""

    def __init__(
        self,
        on_dictation_press: Callable[[], None],
        on_dictation_release: Callable[[], None],
        on_assistant_press: Callable[[], None],
        on_assistant_release: Callable[[], None],
        dictation_key: Any,
        assistant_key: Any,
    ) -> None:
        self.on_dictation_press = on_dictation_press
        self.on_dictation_release = on_dictation_release
        self.on_assistant_press = on_assistant_press
        self.on_assistant_release = on_assistant_release
        self.dictation_key = dictation_key
        self.assistant_key = assistant_key

        self.listener: Any = None
        self.dictation_active: bool = False
        self.assistant_active: bool = False

    def _on_press(self, key: Any) -> None:
        """Handle key press."""
        try:
            if (
                key == self.dictation_key
                and not self.dictation_active
                and not self.assistant_active
            ):
                self.dictation_active = True
                self.on_dictation_press()
            elif (
                key == self.assistant_key
                and not self.assistant_active
                and not self.dictation_active
            ):
                self.assistant_active = True
                self.on_assistant_press()
        except AttributeError:
            pass

    def _on_release(self, key: Any) -> None:
        """Handle key release."""
        try:
            if key == self.dictation_key and self.dictation_active:
                self.dictation_active = False
                self.on_dictation_release()
            elif key == self.assistant_key and self.assistant_active:
                self.assistant_active = False
                self.on_assistant_release()
        except AttributeError:
            pass

    def start(self) -> None:
        """Start the pynput listener."""
        from pynput import keyboard

        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.start()

    def stop(self) -> None:
        """Stop the listener."""
        if self.listener:
            self.listener.stop()

    def join(self) -> None:
        """Wait for the listener to finish."""
        if self.listener:
            self.listener.join()

    def update_keys(self, dictation_key_string: str, assistant_key_string: str) -> None:
        """Update hotkeys without restarting the listener."""
        from pynput.keyboard import Key

        # Parse key strings to pynput Key objects
        def parse_key(key_string: str) -> Any:
            if key_string.startswith("Key."):
                key_name = key_string[4:]
                return getattr(Key, key_name)
            return key_string

        self.dictation_key = parse_key(dictation_key_string)
        self.assistant_key = parse_key(assistant_key_string)
        logger.info("Hotkeys updated: dictation=%s, assistant=%s", dictation_key_string, assistant_key_string)


def create_hotkey_listener(
    on_dictation_press: Callable[[], None],
    on_dictation_release: Callable[[], None],
    on_assistant_press: Callable[[], None],
    on_assistant_release: Callable[[], None],
    dictation_key: Any = None,
    assistant_key: Any = None,
    dictation_key_string: str = "Key.ctrl_r",
    assistant_key_string: str = "Key.alt_r",
) -> HotkeyListener:
    """Create the appropriate hotkey listener for the current display server.

    Args:
        on_dictation_press: Callback when dictation key is pressed
        on_dictation_release: Callback when dictation key is released
        on_assistant_press: Callback when assistant key is pressed
        on_assistant_release: Callback when assistant key is released
        dictation_key: pynput Key for dictation (only used on X11)
        assistant_key: pynput Key for assistant (only used on X11)
        dictation_key_string: Key string from config (e.g., "Key.ctrl_r")
        assistant_key_string: Key string from config (e.g., "Key.alt_r")

    Returns:
        HotkeyListener instance appropriate for the display server
    """
    if is_wayland():
        logger.info("Wayland detected - using evdev for hotkeys")
        dictation_code = EvdevHotkeyListener.get_key_code(dictation_key_string)
        assistant_code = EvdevHotkeyListener.get_key_code(assistant_key_string)
        logger.info("Dictation key: %s (code %s)", dictation_key_string, dictation_code)
        logger.info("Assistant key: %s (code %s)", assistant_key_string, assistant_code)
        return EvdevHotkeyListener(
            on_dictation_press=on_dictation_press,
            on_dictation_release=on_dictation_release,
            on_assistant_press=on_assistant_press,
            on_assistant_release=on_assistant_release,
            dictation_key_code=dictation_code,
            assistant_key_code=assistant_code,
        )
    else:
        logger.info("X11 detected - using pynput for hotkeys")
        return PynputHotkeyListener(
            on_dictation_press=on_dictation_press,
            on_dictation_release=on_dictation_release,
            on_assistant_press=on_assistant_press,
            on_assistant_release=on_assistant_release,
            dictation_key=dictation_key,
            assistant_key=assistant_key,
        )
