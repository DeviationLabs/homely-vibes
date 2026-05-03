"""Global hotkey listener for push-to-talk recording.

Uses pynput to detect when the configured key (default: Right Option / alt_r) is
held down or released. Fires callbacks without consuming the key event so the
key still works normally in other apps.

macOS requirement: the process needs Accessibility permission.
  System Settings → Privacy & Security → Accessibility → add Terminal / your app.
  If permission is missing, pynput silently fails — we detect this at startup and
  print an actionable error message.

Usage:
    listener = HotkeyListener(on_press=start_cb, on_release=stop_cb)
    listener.start()   # non-blocking, runs in daemon thread
    ...
    listener.stop()

The hotkey key name comes from cfg.voice_notes.hotkey and maps to a pynput Key
enum value (e.g. "right_option" → Key.alt_r, "f5" → Key.f5).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Optional

from lib.config import get_config
from lib.logger import get_logger

# TODO: add pynput to optional voice deps before uncommenting
# from pynput import keyboard
# from pynput.keyboard import Key, KeyCode

cfg = get_config()
logger = get_logger(__name__)

# Maps config string → pynput Key attribute name.
# Extend this dict to support additional keys.
_KEY_MAP: dict[str, str] = {
    "right_option": "alt_r",
    "left_option": "alt_l",
    "right_command": "cmd_r",
    "f5": "f5",
    "f13": "f13",
}


class HotkeyListener:
    """Non-blocking push-to-talk key listener.

    Implementation plan:
      1. Resolve cfg.voice_notes.hotkey → pynput Key via _KEY_MAP.
      2. Create a pynput.keyboard.Listener with on_press / on_release callbacks.
      3. In on_press: if event key matches target key AND not already held,
         set _held=True and call the on_press callback once (edge-triggered).
      4. In on_release: if _held, set _held=False and call on_release callback.
      5. Run listener in daemon thread so it doesn't block process exit.
      6. Detect Accessibility permission failure: pynput raises or returns no
         events → check by inspecting listener.running after a short sleep.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._listener: Optional[object] = None  # pynput Listener, typed as Any
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start listening in a background daemon thread.

        TODO:
          - Resolve hotkey key from cfg.voice_notes.hotkey via _KEY_MAP.
          - Instantiate pynput.keyboard.Listener(on_press=..., on_release=...).
          - Start listener in daemon thread.
          - After 0.5s, check listener.running; if False, log actionable error
            about Accessibility permission and raise RuntimeError.
        """
        logger.info("HotkeyListener.start: hotkey=%s", cfg.voice_notes.hotkey)
        # TODO: implement

    def stop(self) -> None:
        """Stop the listener and join the background thread.

        TODO: call listener.stop(), join thread with timeout=2s.
        """
        logger.info("HotkeyListener.stop")
        # TODO: implement
