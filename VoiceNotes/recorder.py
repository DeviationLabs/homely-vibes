"""Push-to-talk audio recorder with streaming chunk output.

State machine:
  IDLE ──[key_down]──► RECORDING ──[key_up]──► TRANSCRIBING ──[done]──► IDLE
                           │
                      every chunk_duration_s seconds
                           │
                      emit chunk (numpy array) via on_chunk callback

The recorder owns the sounddevice InputStream. Audio is captured at 16kHz mono
(the sample rate expected by parakeet-mlx and Whisper). While in RECORDING
state, audio frames are buffered. Every chunk_duration_s seconds a chunk is
carved off and emitted via on_chunk so the Transcriber can process it
incrementally (real-time streaming to file while recording continues).

On key_release, any remaining buffered audio is flushed as a final chunk.
The recorder then transitions to TRANSCRIBING and waits for the caller to
call recording_done() to return to IDLE.

Usage:
    def handle_chunk(audio: np.ndarray) -> None:
        text = transcriber.transcribe(audio)
        writer.append(text)

    rec = AudioRecorder(on_chunk=handle_chunk)
    rec.start_recording()   # called by hotkey on_press
    rec.stop_recording()    # called by hotkey on_release
    rec.recording_done()    # called after last chunk transcribed
"""

from __future__ import annotations

import enum
import threading
from collections.abc import Callable
from typing import Optional

import numpy as np

from lib.config import get_config
from lib.logger import get_logger

# TODO: add sounddevice to optional voice deps before uncommenting
# import sounddevice as sd

cfg = get_config()
logger = get_logger(__name__)


class RecorderState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class AudioRecorder:
    """Push-to-talk audio recorder with streaming chunk callbacks.

    Implementation plan:
      __init__:
        - Store on_chunk callback and config values.
        - Pre-compute chunk_frames = sample_rate * chunk_duration_s.
        - Initialize _buffer: list[np.ndarray] = [].
        - Initialize _state = RecorderState.IDLE.
        - Initialize _stream = None (sounddevice InputStream, lazy).
        - Start a background timer thread that fires _emit_chunk() every
          chunk_duration_s while in RECORDING state.

      start_recording():
        - Guard: if not IDLE, log warning and return (no re-entrant recording).
        - Open sounddevice InputStream(samplerate, channels, dtype='float32',
          callback=_audio_callback).
        - Set state = RECORDING.
        - Start chunk timer.

      _audio_callback(indata, frames, time, status):
        - Called by sounddevice on each audio block (~10ms).
        - If state == RECORDING: append indata.copy() to _buffer.
        - This runs in sounddevice's audio thread — keep it fast, no locks.

      _emit_chunk():
        - Called every chunk_duration_s by timer, and once on stop_recording().
        - Concatenate and clear _buffer (swap with []).
        - If audio has content, call on_chunk(audio_array).

      stop_recording():
        - Guard: if not RECORDING, return.
        - Stop chunk timer.
        - Flush remaining buffer via _emit_chunk().
        - Stop sounddevice stream.
        - Set state = TRANSCRIBING.

      recording_done():
        - Called by orchestrator after last chunk processed.
        - Set state = IDLE.
    """

    def __init__(self, on_chunk: Callable[[np.ndarray], None]) -> None:
        self._on_chunk = on_chunk
        self._sample_rate: int = cfg.voice_notes.sample_rate
        self._channels: int = cfg.voice_notes.channels
        self._chunk_duration: float = cfg.voice_notes.chunk_duration_s
        self._chunk_frames = int(self._sample_rate * self._chunk_duration)

        self._buffer: list[np.ndarray] = []
        self._state = RecorderState.IDLE
        self._stream: Optional[object] = None  # sd.InputStream
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> RecorderState:
        return self._state

    def start_recording(self) -> None:
        """Transition IDLE → RECORDING; open audio stream and start chunk timer.

        TODO: implement per class docstring plan.
        """
        if self._state != RecorderState.IDLE:
            logger.warning("start_recording called in state %s, ignoring", self._state)
            return
        logger.info("AudioRecorder: start recording")
        # TODO: implement

    def stop_recording(self) -> None:
        """Transition RECORDING → TRANSCRIBING; flush final chunk.

        TODO: implement per class docstring plan.
        """
        if self._state != RecorderState.RECORDING:
            logger.warning("stop_recording called in state %s, ignoring", self._state)
            return
        logger.info("AudioRecorder: stop recording, flushing buffer")
        # TODO: implement

    def recording_done(self) -> None:
        """Transition TRANSCRIBING → IDLE.

        TODO: set self._state = RecorderState.IDLE.
        """
        self._state = RecorderState.IDLE

    def _emit_chunk(self) -> None:
        """Swap buffer, concatenate audio, fire on_chunk callback.

        TODO: implement per class docstring plan.
        """
        # TODO: implement

    def _start_timer(self) -> None:
        """Schedule next _emit_chunk call after chunk_duration_s seconds.

        TODO: use threading.Timer; re-schedule only if still RECORDING.
        """
        # TODO: implement
