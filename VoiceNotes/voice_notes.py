"""VoiceNotes — push-to-talk voice transcription menu-bar app.

This is the main entry point. It runs as a rumps macOS menu-bar application
and orchestrates the four components:

  HotkeyListener  ──press──►  AudioRecorder  ──chunk──►  Transcriber  ──text──►  SessionWriter
                  ◄─release──                                          ◄─done────

Menu bar states:
  🎙 VoiceNotes      — IDLE, waiting for hotkey
  🔴 Recording...    — key held, audio being captured + streaming to file
  ⏳ Loading model   — first press: parakeet-mlx loading (~3-5s)
  ⏳ Transcribing... — key released, final chunk being processed
  ✅ Saved           — session file written (shown for 2s, then back to idle)

Menu items:
  • Open today's notes folder   → opens ~/bin/knowledge/notes in Finder
  • Show last session           → opens last written file in default app
  • ─────────────────
  • Quit

macOS permission notes:
  - Accessibility: required for pynput global hotkeys
    System Settings → Privacy & Security → Accessibility → add Terminal
  - Microphone: required for sounddevice audio capture
    System Settings → Privacy & Security → Microphone → add Terminal

Run:
    uv run python VoiceNotes/voice_notes.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from lib.config import get_config
from lib.logger import get_logger
from VoiceNotes.hotkey import HotkeyListener
from VoiceNotes.recorder import AudioRecorder
from VoiceNotes.transcriber import Transcriber
from VoiceNotes.writer import SessionWriter

# TODO: add rumps to optional voice deps before uncommenting
# import rumps

cfg = get_config()
logger = get_logger(__name__)

IDLE_TITLE = "🎙 VoiceNotes"
RECORDING_TITLE = "🔴 Recording..."
LOADING_TITLE = "⏳ Loading model..."
TRANSCRIBING_TITLE = "⏳ Transcribing..."
SAVED_TITLE = "✅ Saved"
SAVED_DISPLAY_SECONDS = 2


class VoiceNotesApp:  # TODO: inherit from rumps.App when dep available
    """Menu-bar orchestrator for push-to-talk voice transcription.

    Implementation plan:
      __init__:
        - Call super().__init__("VoiceNotes", title=IDLE_TITLE).
        - Instantiate Transcriber, SessionWriter, AudioRecorder(on_chunk=_on_chunk).
        - Instantiate HotkeyListener(on_press=_on_key_press, on_release=_on_key_release).
        - Build menu items: "Open notes folder", "Show last session", None (separator), quit.

      _on_key_press():
        - If recorder.state != IDLE, return (already recording).
        - If not transcriber.is_loaded: set title=LOADING_TITLE in main thread.
        - Open SessionWriter.
        - Call recorder.start_recording().
        - Set title=RECORDING_TITLE.

      _on_chunk(audio: np.ndarray):
        - Called from AudioRecorder's timer thread for each 3s chunk.
        - text = transcriber.transcribe(audio).
        - If text: writer.append(text + " ").
        - (No title change here — we're mid-recording.)

      _on_key_release():
        - Set title=TRANSCRIBING_TITLE.
        - recorder.stop_recording() → triggers final _on_chunk.
        - writer.close().
        - recorder.recording_done().
        - Show SAVED_TITLE for SAVED_DISPLAY_SECONDS, then restore IDLE_TITLE.

      _open_notes_folder(sender):  rumps menu click handler
        - subprocess.Popen(["open", str(notes_dir)]).

      _show_last_session(sender):  rumps menu click handler
        - Find most recent .md file in notes_dir.
        - subprocess.Popen(["open", str(path)]).

    Thread safety:
      - _on_chunk runs in AudioRecorder's background timer thread.
      - _on_key_press / _on_key_release run in pynput's keyboard thread.
      - rumps menu callbacks run on the main thread.
      - Use threading.Lock in AudioRecorder buffer (handled there).
      - Title updates must be dispatched to main thread via rumps.App.title setter
        (rumps is not thread-safe for title updates — wrap in a Timer(0, ...) trick).
    """

    def __init__(self) -> None:
        # TODO: super().__init__("VoiceNotes", title=IDLE_TITLE)
        self._transcriber = Transcriber()
        self._writer = SessionWriter()
        self._recorder = AudioRecorder(on_chunk=self._on_chunk)
        self._hotkey = HotkeyListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._notes_dir = Path(cfg.voice_notes.notes_dir).expanduser()

    def run(self) -> None:
        """Start hotkey listener and run rumps event loop.

        TODO:
          - self._hotkey.start()
          - self.menu = [...] (build rumps menu)
          - self.run() (rumps.App.run — blocks until quit)
        """
        logger.info("VoiceNotesApp starting")
        self._hotkey.start()
        # TODO: rumps event loop

    def _on_key_press(self) -> None:
        """Called by HotkeyListener when recording key is pressed.

        TODO: implement per class docstring plan.
        """
        logger.debug("key press → start recording")
        # TODO: implement

    def _on_key_release(self) -> None:
        """Called by HotkeyListener when recording key is released.

        TODO: implement per class docstring plan.
        """
        logger.debug("key release → finalize recording")
        # TODO: implement

    def _on_chunk(self, _audio: np.ndarray) -> None:
        """Called by AudioRecorder every chunk_duration_s with audio data.

        TODO: implement per class docstring plan (rename _audio → audio).
        """
        # TODO: transcribe and append to writer

    def _open_notes_folder(self, _sender: object) -> None:
        """Open notes directory in Finder.

        TODO: subprocess.Popen(["open", str(self._notes_dir)])
        """
        subprocess.Popen(["open", str(self._notes_dir)])  # noqa: S603,S607

    def _show_last_session(self, _sender: object) -> None:
        """Open the most recently written session file.

        TODO:
          - Glob self._notes_dir for *.md, sort by mtime, open latest.
          - If no files exist, show rumps.alert("No notes yet.").
        """
        # TODO: implement


def main() -> None:
    """Entry point."""
    VoiceNotesApp().run()


if __name__ == "__main__":
    main()
