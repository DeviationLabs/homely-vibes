"""Global hotkey listener for push-to-talk recording.

Uses pynput to monitor keyboard events globally (across all apps). When the
configured key is held, fires on_press once (edge-triggered). When released,
fires on_release. The key continues to function normally in other apps.

macOS requirement: Accessibility permission for the terminal/app.
  System Settings → Privacy & Security → Accessibility → add Terminal (or your app)

If permission is absent, pynput's listener starts but never fires events.
We detect this by checking listener.running after a brief warmup and printing
an actionable error rather than silently doing nothing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Optional

from lib.config import get_config
from lib.logger import get_logger

cfg = get_config()
logger = get_logger(__name__)

# Maps cfg.voice_notes.hotkey string → pynput Key attribute name
_KEY_MAP: dict[str, str] = {
    "right_option": "alt_r",
    "left_option": "alt_l",
    "right_command": "cmd_r",
    "left_command": "cmd_l",
    "right_ctrl": "ctrl_r",
    "f5": "f5",
    "f13": "f13",
    "f14": "f14",
}

_ACCESSIBILITY_MSG = """
⚠️  VoiceNotes: Accessibility permission required for global hotkeys.

   System Settings → Privacy & Security → Accessibility
   → Click the + button → add Terminal (or your terminal app)
   → Restart VoiceNotes

Without this permission, the hotkey will not respond.
"""


class HotkeyListener:
    """Non-blocking push-to-talk key listener.

    Runs pynput Listener in a daemon thread. Fires on_press / on_release
    callbacks once per hold cycle (edge-triggered, not repeated while held).
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._listener: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._target_key: Optional[object] = None  # pynput Key enum value

    def start(self) -> None:
        """Start listening in a daemon thread. Non-blocking."""
        from pynput import keyboard  # type: ignore[import]
        from pynput.keyboard import Key  # type: ignore[import]

        hotkey_name = cfg.voice_notes.hotkey
        key_attr = _KEY_MAP.get(hotkey_name, hotkey_name)
        try:
            self._target_key = getattr(Key, key_attr)
        except AttributeError:
            raise ValueError(f"Unknown hotkey: {hotkey_name!r} (mapped to Key.{key_attr})")

        def on_press(key: object) -> None:
            if key == self._target_key and not self._held:
                self._held = True
                self._on_press()

        def on_release(key: object) -> None:
            if key == self._target_key and self._held:
                self._held = False
                self._on_release()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._thread = threading.Thread(target=self._listener.run, daemon=True)  # type: ignore[union-attr]
        self._thread.start()

        # Give pynput 0.5s to start; if it doesn't fire events, Accessibility is missing
        time.sleep(0.5)
        if not self._listener.running:  # type: ignore[union-attr]
            logger.error("HotkeyListener: pynput listener not running — check Accessibility")
            print(_ACCESSIBILITY_MSG)

        logger.info("HotkeyListener started: hotkey=%s (Key.%s)", hotkey_name, key_attr)

    def stop(self) -> None:
        """Stop the listener and join the background thread."""
        if self._listener is not None:
            self._listener.stop()  # type: ignore[union-attr]
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("HotkeyListener stopped")
