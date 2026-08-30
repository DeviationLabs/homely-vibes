"""Tests for VoiceNotes module.

Test strategy:
  - writer.py: full unit tests using tmp_path — no external deps needed.
  - recorder.py: state machine tests via stream_factory injection (no real audio).
  - transcriber.py: validation tests with injected mock model (no real model load).
  - hotkey.py: key resolution logic only (no pynput events, no Accessibility perms).

Per CLAUDE.md: NEVER use patch() — inject via constructor parameters instead.
AudioRecorder.stream_factory and Transcriber._model injection are the DI seams.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np

from VoiceNotes.recorder import AudioRecorder, RecorderState
from VoiceNotes.transcriber import Transcriber
from VoiceNotes.writer import SessionWriter


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_writer(tmp_path: Path) -> SessionWriter:
    """SessionWriter pointed at tmp_path, bypassing cfg."""
    w = SessionWriter.__new__(SessionWriter)
    w._notes_dir = tmp_path
    w._path = None
    w._file = None
    w._session_start = None
    return w


def _fake_stream_factory(**_kwargs: Any) -> MagicMock:
    """Returns a mock sounddevice.InputStream that does nothing."""
    m = MagicMock()
    m.start.return_value = None
    m.stop.return_value = None
    m.close.return_value = None
    return m


def _fake_vad_factory(_aggressiveness: int) -> MagicMock:
    """Returns a mock webrtcvad.Vad that always reports silence (VAD loop exits on sentinel)."""
    m = MagicMock()
    m.is_speech.return_value = False
    return m


# ── SessionWriter ─────────────────────────────────────────────────────────────


class TestSessionWriter:
    def test_open_creates_file(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        assert path.exists()

    def test_open_returns_path_inside_notes_dir(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        w.close()
        assert path.parent == tmp_path

    def test_open_filename_has_md_extension(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        w.close()
        assert path.suffix == ".md"

    def test_open_writes_timestamp_header(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        w.close()
        content = path.read_text()
        assert content.startswith("## ")

    def test_append_writes_text_immediately(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        w.append("hello world ")
        content = path.read_text()
        assert "hello world" in content
        w.close()

    def test_multiple_appends_accumulate(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        w.append("foo ")
        w.append("bar ")
        content = path.read_text()
        assert "foo" in content and "bar" in content
        w.close()

    def test_close_writes_separator(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        path = w.open()
        w.close()
        content = path.read_text()
        assert "---" in content

    def test_close_resets_is_open(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        w.open()
        w.close()
        assert not w.is_open

    def test_append_before_open_does_not_raise(self, tmp_path: Path) -> None:
        w = _make_writer(tmp_path)
        w.append("should not raise")  # logs warning, returns

    def test_notes_dir_created_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        w = _make_writer(nested)
        w.open()
        assert nested.exists()
        w.close()


# ── AudioRecorder state machine ───────────────────────────────────────────────


class TestAudioRecorderStateMachine:
    """Use stream_factory injection to avoid real sounddevice + VAD dependency."""

    def _recorder(self) -> tuple[AudioRecorder, list[np.ndarray]]:
        chunks: list[np.ndarray] = []
        rec = AudioRecorder(
            on_chunk=chunks.append,
            stream_factory=_fake_stream_factory,
            vad_factory=_fake_vad_factory,
        )
        return rec, chunks

    def test_initial_state_is_idle(self) -> None:
        rec, _ = self._recorder()
        assert rec.state == RecorderState.IDLE

    def test_start_recording_transitions_to_recording(self) -> None:
        rec, _ = self._recorder()
        rec.start_recording()
        assert rec.state == RecorderState.RECORDING
        rec.stop_recording()  # clean up thread

    def test_double_start_stays_recording(self) -> None:
        rec, _ = self._recorder()
        rec.start_recording()
        rec.start_recording()  # no-op
        assert rec.state == RecorderState.RECORDING
        rec.stop_recording()

    def test_stop_recording_returns_to_idle(self) -> None:
        rec, _ = self._recorder()
        rec.start_recording()
        rec.stop_recording()
        assert rec.state == RecorderState.IDLE

    def test_stop_without_start_is_safe(self) -> None:
        rec, _ = self._recorder()
        rec.stop_recording()  # logs warning, does not raise
        assert rec.state == RecorderState.IDLE


# ── Transcriber validation ────────────────────────────────────────────────────


class TestTranscriberValidation:
    def test_is_loaded_false_before_transcribe(self) -> None:
        t = Transcriber()
        assert not t.is_loaded

    def test_empty_audio_returns_empty_string(self) -> None:
        t = Transcriber()
        # inject mock model so we don't load whisper.cpp
        t._model = MagicMock()
        result = t.transcribe(np.array([], dtype=np.float32))
        assert result == ""
        t._model.transcribe.assert_not_called()

    def test_short_audio_returns_empty_string(self) -> None:
        t = Transcriber()
        t._model = MagicMock()
        # 50 samples at 16kHz = 3ms — below 100ms threshold
        audio = np.zeros(50, dtype=np.float32)
        result = t.transcribe(audio)
        assert result == ""
        t._model.transcribe.assert_not_called()

    def test_mock_model_result_joined(self) -> None:
        t = Transcriber()
        seg1, seg2 = MagicMock(), MagicMock()
        seg1.text = " hello "
        seg2.text = " world "
        t._model = MagicMock()
        t._model.transcribe.return_value = [seg1, seg2]
        audio = np.zeros(int(16000 * 0.5), dtype=np.float32)  # 0.5s
        result = t.transcribe(audio)
        assert result == "hello world"

    def test_is_loaded_true_after_model_injected(self) -> None:
        t = Transcriber()
        t._model = MagicMock()
        assert t.is_loaded
