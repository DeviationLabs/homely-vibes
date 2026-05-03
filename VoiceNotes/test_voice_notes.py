"""Tests for VoiceNotes module.

Test strategy:
  - recorder.py: unit-test the state machine transitions. No real audio needed.
    AudioRecorder accepts on_chunk callback, so we can inject a mock and assert
    it's called with the right data when we manually push frames.

  - writer.py: unit-test file creation, append, and close. Uses tmp_path fixture
    (pytest built-in) to avoid writing to real notes directory.

  - transcriber.py: unit-test model selection logic and input validation only.
    DO NOT load real models in tests (slow, requires deps). The transcriber
    accepts a DI seam: set _model to a mock after construction.

  - hotkey.py: integration behavior not tested (requires Accessibility perms +
    real pynput). Only test the key name resolution logic.

Per CLAUDE.md:
  - NEVER use patch() — inject dependencies as parameters instead.
  - Temperature 0 is NOT deterministic — test observable behavior, not LLM output.
  - Complex logic (state machine) warrants TDD.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from VoiceNotes.recorder import AudioRecorder, RecorderState
from VoiceNotes.transcriber import Transcriber
from VoiceNotes.writer import SessionWriter


# ── AudioRecorder state machine tests ────────────────────────────────────────


class TestAudioRecorderStateMachine:
    """Validate RecorderState transitions without real audio hardware.

    TODO: once recorder.py is implemented, these tests should pass.
    The tests are written against the public API (start_recording,
    stop_recording, recording_done, state property).
    """

    def test_initial_state_is_idle(self) -> None:
        chunks: list[np.ndarray] = []
        rec = AudioRecorder(on_chunk=chunks.append)
        assert rec.state == RecorderState.IDLE

    def test_start_recording_transitions_to_recording(self) -> None:
        """TODO: will pass once start_recording() is implemented."""
        pytest.skip("Not yet implemented")

    def test_stop_recording_transitions_to_transcribing(self) -> None:
        """TODO: will pass once stop_recording() is implemented."""
        pytest.skip("Not yet implemented")

    def test_recording_done_transitions_to_idle(self) -> None:
        """TODO: will pass once stop_recording() + recording_done() are implemented."""
        pytest.skip("Not yet implemented")

    def test_double_start_is_idempotent(self) -> None:
        """Calling start_recording() twice should not change state to a broken value."""
        pytest.skip("Not yet implemented")

    def test_on_chunk_called_per_chunk_duration(self) -> None:
        """Verify on_chunk fires ~N times for N * chunk_duration_s of recording.

        Strategy: replace the sounddevice stream with a test double that
        immediately injects pre-fabricated numpy frames.
        TODO: requires injection point in AudioRecorder for the stream factory.
        """
        pytest.skip("Not yet implemented")


# ── SessionWriter tests ───────────────────────────────────────────────────────


class TestSessionWriter:
    """Test file creation, append, and close using pytest tmp_path."""

    def _make_writer(self, tmp_path: Path) -> SessionWriter:
        """Create a SessionWriter pointed at tmp_path (no real cfg needed)."""
        writer = SessionWriter.__new__(SessionWriter)
        writer._notes_dir = tmp_path
        writer._path = None
        writer._file = None
        writer._session_start = None
        return writer

    def test_open_creates_file(self, tmp_path: Path) -> None:
        """TODO: will pass once open() is implemented."""
        pytest.skip("Not yet implemented")

    def test_open_returns_path_in_notes_dir(self, tmp_path: Path) -> None:
        """TODO: will pass once open() is implemented."""
        pytest.skip("Not yet implemented")

    def test_append_writes_text_to_file(self, tmp_path: Path) -> None:
        """TODO: will pass once open() + append() are implemented."""
        pytest.skip("Not yet implemented")

    def test_append_without_open_does_not_raise(self, tmp_path: Path) -> None:
        """Calling append() before open() should log a warning and not raise."""
        writer = self._make_writer(tmp_path)
        writer.append("hello")  # should not raise

    def test_close_writes_separator(self, tmp_path: Path) -> None:
        """TODO: will pass once open() + close() are implemented."""
        pytest.skip("Not yet implemented")

    def test_close_resets_is_open(self, tmp_path: Path) -> None:
        """TODO: will pass once close() is implemented."""
        pytest.skip("Not yet implemented")

    def test_notes_dir_created_if_missing(self, tmp_path: Path) -> None:
        """TODO: open() should create the notes dir if it doesn't exist."""
        pytest.skip("Not yet implemented")


# ── Transcriber validation tests ─────────────────────────────────────────────


class TestTranscriberValidation:
    """Test input validation and backend selection logic.

    These tests do NOT load real models. We inject a mock model after
    construction to avoid the ~3-5s model load in CI.
    """

    def test_invalid_backend_raises_value_error(self) -> None:
        """TODO: will pass once __init__ validates backend."""
        pytest.skip("Not yet implemented")

    def test_is_loaded_false_before_transcribe(self) -> None:
        t = Transcriber()
        assert not t.is_loaded

    def test_transcribe_with_mock_model_returns_string(self) -> None:
        """Inject mock model to bypass real model loading.

        TODO: will pass once transcribe() dispatches to _transcribe_parakeet
        or _transcribe_whisper. Set t._model = MagicMock() with a configured
        return value to verify the routing logic.
        """
        pytest.skip("Not yet implemented")

    def test_transcribe_empty_audio_returns_empty_string(self) -> None:
        """Empty audio array should return '' without crashing.

        TODO: will pass once transcribe() has input validation.
        """
        pytest.skip("Not yet implemented")
