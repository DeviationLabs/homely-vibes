"""VoiceNotes — local push-to-talk voice transcription to markdown files.

Architecture:
  voice_notes.py  — rumps menu-bar App; orchestrates all components
  hotkey.py       — pynput global hotkey listener (hold Right Option to record)
  recorder.py     — sounddevice audio capture with push-to-talk state machine
  transcriber.py  — parakeet-mlx STT engine (mlx-whisper fallback)
  writer.py       — per-session markdown file writer with real-time append

Install deps:  uv sync --extra voice
Run:           uv run python VoiceNotes/voice_notes.py
"""

from VoiceNotes.recorder import AudioRecorder, RecorderState
from VoiceNotes.transcriber import Transcriber
from VoiceNotes.writer import SessionWriter

__all__ = ["AudioRecorder", "RecorderState", "Transcriber", "SessionWriter"]
