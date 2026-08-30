"""VoiceNotes — push-to-talk voice transcription menu-bar app.

Entry point. Runs as a rumps macOS menu-bar application.

Data flow:
  Hold ⌥right → HotkeyListener._on_press → AudioRecorder.start_recording()
                                                    │
                                    sounddevice (Metal audio) → VAD thread
                                                    │
                                      phrase detected → Transcriber.transcribe()
                                                    │
                                            SessionWriter.append(text)
                                                    │
                                         word appears in notes file
  Release ⌥right → HotkeyListener._on_release → AudioRecorder.stop_recording()
                                                    │ (flushes final phrase)
                                           SessionWriter.close()

Thread safety:
  - Hotkey callbacks: pynput thread
  - on_chunk callbacks: VAD thread (inside AudioRecorder)
  - rumps callbacks (menu clicks): main thread
  - Title updates from background threads: dispatched via rumps.Timer(interval=0)

Run:
    uv run python VoiceNotes/voice_notes.py

First-run permissions:
    Accessibility: System Settings → Privacy & Security → Accessibility → add Terminal
    Microphone:    System Settings → Privacy & Security → Microphone → add Terminal
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import rumps  # type: ignore[import]
from PyObjCTools import AppHelper  # type: ignore[import]

from lib.config import get_config
from lib.logger import get_logger
from VoiceNotes.hotkey import HotkeyListener
from VoiceNotes.recorder import AudioRecorder
from VoiceNotes.transcriber import Transcriber
from VoiceNotes.writer import SessionWriter

cfg = get_config()
logger = get_logger(__name__)

_IDLE = "🎙 VoiceNotes"
_LOADING = "⏳ Loading model..."
_RECORDING = "🔴 Recording..."
_SAVED = "✅ Saved"
_SAVED_SECS = 2


class VoiceNotesApp(rumps.App):
    """Menu-bar orchestrator for push-to-talk voice transcription."""

    def __init__(self) -> None:
        super().__init__("VoiceNotes", title=_IDLE)
        self._transcriber = Transcriber()
        self._writer = SessionWriter()
        self._recorder = AudioRecorder(on_chunk=self._on_chunk)
        self._hotkey = HotkeyListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._notes_dir = Path(cfg.voice_notes.notes_dir).expanduser()
        self._last_path: Path | None = None

        self.menu = [
            rumps.MenuItem("Open notes folder", callback=self._open_notes_folder),
            rumps.MenuItem("Show last session", callback=self._show_last_session),
            None,  # separator
        ]

    def run(self) -> None:  # type: ignore[override]
        self._hotkey.start()
        logger.info("VoiceNotesApp running — hold %s to record", cfg.voice_notes.hotkey)
        super().run()

    # ── hotkey callbacks (pynput thread) ──────────────────────────────────────

    def _on_key_press(self) -> None:
        if not self._transcriber.is_loaded:
            self._set_title(_LOADING)
        self._writer.open()
        self._recorder.start_recording()
        self._set_title(_RECORDING)
        logger.debug("key pressed — recording started")

    def _on_key_release(self) -> None:
        # stop_recording() flushes final phrase → triggers one last _on_chunk
        self._recorder.stop_recording()
        self._writer.close()
        self._last_path = self._writer.path  # path is None after close; grab before
        self._set_title(_SAVED)
        # restore idle title after 2s — schedule on main thread
        AppHelper.callLater(_SAVED_SECS, self._restore_idle)
        logger.debug("key released — session saved")

    def _restore_idle(self) -> None:
        self.title = _IDLE

    # ── VAD thread callback ───────────────────────────────────────────────────

    def _on_chunk(self, audio: np.ndarray) -> None:
        """Called from VAD thread for each detected phrase. Transcribes and appends."""
        text = self._transcriber.transcribe(audio)
        if text:
            self._writer.append(text + " ")
            logger.debug("appended: %r", text[:60])

    # ── menu callbacks (main thread) ──────────────────────────────────────────

    @rumps.clicked("Open notes folder")
    def _open_notes_folder(self, _: rumps.MenuItem) -> None:
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["open", str(self._notes_dir)])  # noqa: S603,S607

    @rumps.clicked("Show last session")
    def _show_last_session(self, _: rumps.MenuItem) -> None:
        files = sorted(self._notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            rumps.alert("No voice notes yet. Hold ⌥right to start recording.")
            return
        subprocess.Popen(["open", str(files[0])])  # noqa: S603,S607

    # ── thread-safe title update ──────────────────────────────────────────────

    def _set_title(self, title: str) -> None:
        """Update menu bar title from any thread by dispatching to the main runloop.

        AppHelper.callAfter() schedules `func` on the main thread via PyObjC's
        runloop machinery — required because AppKit (NSStatusItem) is main-thread-only.
        Calling self.title = ... directly from a background thread crashes with
        SIGABRT: "!view->_hasCachedVisibleRect".
        """
        AppHelper.callAfter(lambda: setattr(self, "title", title))


def main() -> None:
    VoiceNotesApp().run()


if __name__ == "__main__":
    main()
