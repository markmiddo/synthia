"""Hotkey handling for Synthia with Wayland and X11 support.

On Wayland: Uses evdev to read directly from input devices.
On X11: Uses pynput for global keyboard hooks.
"""

import os
import threading
from typing import Callable, Optional
from abc import ABC, abstractmethod

from .display import is_wayland


class HotkeyListener(ABC):
    """Abstract base class for hotkey listeners."""

    @abstractmethod
    def start(self):
        """Start listening for hotkeys."""
        pass

    @abstractmethod
    def stop(self):
        """Stop listening for hotkeys."""
        pass

    @abstractmethod
    def join(self):
        """Wait for listener to finish."""
        pass


class EvdevHotkeyListener(HotkeyListener):
    """Hotkey listener using evdev (works on Wayland).

    Requires user to be in 'input' group:
        sudo usermod -aG input $USER
        # Then logout/login
    """

    # Key codes for Right Ctrl and Right Alt
    KEY_RIGHTCTRL = 97
    KEY_RIGHTALT = 100

    def __init__(
        self,
        on_dictation_press: Callable,
        on_dictation_release: Callable,
        on_assistant_press: Callable,
        on_assistant_release: Callable,
    ):
        self.on_dictation_press = on_dictation_press
        self.on_dictation_release = on_dictation_release
        self.on_assistant_press = on_assistant_press
        self.on_assistant_release = on_assistant_release

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.devices = []

    def _find_keyboard_devices(self) -> list:
        """Find all keyboard input devices."""
        try:
            from evdev import InputDevice, list_devices, ecodes

            keyboards = []
            for path in list_devices():
                try:
                    device = InputDevice(path)
                    capabilities = device.capabilities()

                    # Check if device has key events and has our target keys
                    if ecodes.EV_KEY in capabilities:
                        keys = capabilities[ecodes.EV_KEY]
                        if self.KEY_RIGHTCTRL in keys or self.KEY_RIGHTALT in keys:
                            keyboards.append(device)
                            print(f"📎 Found keyboard: {device.name} ({device.path})")
                except (PermissionError, OSError) as e:
                    continue

            return keyboards
        except ImportError:
            print("❌ evdev not installed. Install with: pip install evdev")
            return []

    def _listen(self):
        """Main listening loop for evdev."""
        try:
            from evdev import ecodes
            from selectors import DefaultSelector, EVENT_READ

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
                                if event.code == self.KEY_RIGHTCTRL:
                                    if event.value == 1:  # Press
                                        self.on_dictation_press()
                                    elif event.value == 0:  # Release
                                        self.on_dictation_release()
                                elif event.code == self.KEY_RIGHTALT:
                                    if event.value == 1:  # Press
                                        self.on_assistant_press()
                                    elif event.value == 0:  # Release
                                        self.on_assistant_release()
                    except BlockingIOError:
                        pass

            selector.close()
        except Exception as e:
            print(f"❌ evdev listener error: {e}")

    def start(self):
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

    def stop(self):
        """Stop the listener."""
        self.running = False
        for device in self.devices:
            try:
                device.close()
            except Exception:
                pass

    def join(self):
        """Wait for the listener thread to finish."""
        if self.thread:
            self.thread.join()


class PynputHotkeyListener(HotkeyListener):
    """Hotkey listener using pynput (works on X11)."""

    def __init__(
        self,
        on_dictation_press: Callable,
        on_dictation_release: Callable,
        on_assistant_press: Callable,
        on_assistant_release: Callable,
        dictation_key,
        assistant_key,
    ):
        self.on_dictation_press = on_dictation_press
        self.on_dictation_release = on_dictation_release
        self.on_assistant_press = on_assistant_press
        self.on_assistant_release = on_assistant_release
        self.dictation_key = dictation_key
        self.assistant_key = assistant_key

        self.listener = None
        self.dictation_active = False
        self.assistant_active = False

    def _on_press(self, key):
        """Handle key press."""
        try:
            if key == self.dictation_key and not self.dictation_active and not self.assistant_active:
                self.dictation_active = True
                self.on_dictation_press()
            elif key == self.assistant_key and not self.assistant_active and not self.dictation_active:
                self.assistant_active = True
                self.on_assistant_press()
        except AttributeError:
            pass

    def _on_release(self, key):
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

    def start(self):
        """Start the pynput listener."""
        from pynput import keyboard

        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self.listener.start()

    def stop(self):
        """Stop the listener."""
        if self.listener:
            self.listener.stop()

    def join(self):
        """Wait for the listener to finish."""
        if self.listener:
            self.listener.join()


def create_hotkey_listener(
    on_dictation_press: Callable,
    on_dictation_release: Callable,
    on_assistant_press: Callable,
    on_assistant_release: Callable,
    dictation_key=None,
    assistant_key=None,
) -> HotkeyListener:
    """Create the appropriate hotkey listener for the current display server.

    Args:
        on_dictation_press: Callback when dictation key is pressed
        on_dictation_release: Callback when dictation key is released
        on_assistant_press: Callback when assistant key is pressed
        on_assistant_release: Callback when assistant key is released
        dictation_key: pynput Key for dictation (only used on X11)
        assistant_key: pynput Key for assistant (only used on X11)

    Returns:
        HotkeyListener instance appropriate for the display server
    """
    if is_wayland():
        print("🔧 Wayland detected - using evdev for hotkeys")
        return EvdevHotkeyListener(
            on_dictation_press=on_dictation_press,
            on_dictation_release=on_dictation_release,
            on_assistant_press=on_assistant_press,
            on_assistant_release=on_assistant_release,
        )
    else:
        print("🔧 X11 detected - using pynput for hotkeys")
        return PynputHotkeyListener(
            on_dictation_press=on_dictation_press,
            on_dictation_release=on_dictation_release,
            on_assistant_press=on_assistant_press,
            on_assistant_release=on_assistant_release,
            dictation_key=dictation_key,
            assistant_key=assistant_key,
        )
