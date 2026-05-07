"""Push-to-talk audio recorder with VAD-based phrase streaming.

State machine:
  IDLE ──[start_recording]──► RECORDING ──[stop_recording]──► FLUSHING ──[done]──► IDLE
                                   │
                              VAD detects phrase end
                                   │
                              on_chunk(np.ndarray)   ← caller transcribes immediately

Architecture:
  sounddevice callback thread → Queue[np.ndarray] → VAD processor thread
                                                          │
                                              accumulate speech frames
                                                          │
                                      silence > min_silence_ms → on_chunk(phrase)

webrtcvad operates on 30ms int16 PCM frames at 16kHz. The VAD processor thread
reads frames from the queue, runs VAD, and emits accumulated speech when it
detects a pause ≥ min_silence_ms. This gives phrase-by-phrase output that
feels word-by-word to the user — each phrase lands in the file within ~400ms
of the pause that ends it.
"""

from __future__ import annotations

import enum
import queue
import threading
from collections.abc import Callable
from typing import Optional

import numpy as np

from lib.config import get_config
from lib.logger import get_logger

cfg = get_config()
logger = get_logger(__name__)

# VAD frame parameters (webrtcvad requires exactly 10/20/30ms frames at 16kHz)
_VAD_FRAME_MS = 30
_VAD_FRAME_SAMPLES = int(cfg.voice_notes.sample_rate * _VAD_FRAME_MS / 1000)  # 480

# After this many ms of consecutive silence following speech, emit a chunk
_MIN_SILENCE_MS = 400
_SILENCE_FRAMES_THRESHOLD = _MIN_SILENCE_MS // _VAD_FRAME_MS  # 13 frames

# Guard against emitting near-silence noise (min 200ms of actual speech)
_MIN_SPEECH_FRAMES = 200 // _VAD_FRAME_MS  # 6 frames


class RecorderState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    FLUSHING = "flushing"


class AudioRecorder:
    """Push-to-talk recorder with VAD-driven phrase streaming.

    Accepts on_chunk(audio: np.ndarray) callback — called once per detected
    phrase while the key is held, and once more on key release to flush any
    trailing audio.

    Injection points for testing (avoids monkey-patching per CLAUDE.md):
      stream_factory — replaces sounddevice.InputStream constructor
      vad_factory    — replaces webrtcvad.Vad constructor; receives aggressiveness int
    """

    def __init__(
        self,
        on_chunk: Callable[[np.ndarray], None],
        stream_factory: Optional[Callable[..., object]] = None,
        vad_factory: Optional[Callable[[int], object]] = None,
    ) -> None:
        self._on_chunk = on_chunk
        self._stream_factory = stream_factory
        self._vad_factory = vad_factory
        self._sample_rate: int = cfg.voice_notes.sample_rate
        self._channels: int = cfg.voice_notes.channels
        self._vad_aggressiveness: int = cfg.voice_notes.vad_aggressiveness

        self._state = RecorderState.IDLE
        self._frame_queue: queue.Queue[Optional[np.ndarray]] = queue.Queue()
        self._stream: Optional[object] = None
        self._vad_thread: Optional[threading.Thread] = None

    @property
    def state(self) -> RecorderState:
        return self._state

    def start_recording(self) -> None:
        """Transition IDLE → RECORDING. Opens audio stream and VAD thread."""
        if self._state != RecorderState.IDLE:
            logger.warning("start_recording in state %s — ignored", self._state)
            return

        self._state = RecorderState.RECORDING
        self._vad_thread = threading.Thread(target=self._vad_loop, daemon=True)
        self._vad_thread.start()

        if self._stream_factory is not None:
            factory = self._stream_factory
        else:
            import sounddevice as sd  # lazy import — only when no test double provided

            factory = sd.InputStream
        self._stream = factory(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=_VAD_FRAME_SAMPLES,  # deliver exactly one VAD frame at a time
            callback=self._audio_callback,
        )
        self._stream.start()  # type: ignore[union-attr]
        logger.info(
            "AudioRecorder: recording started (VAD aggressiveness=%d)", self._vad_aggressiveness
        )

    def stop_recording(self) -> None:
        """Transition RECORDING → FLUSHING. Stops stream, signals VAD thread to flush."""
        if self._state != RecorderState.RECORDING:
            logger.warning("stop_recording in state %s — ignored", self._state)
            return

        self._state = RecorderState.FLUSHING

        if self._stream is not None:
            self._stream.stop()  # type: ignore[union-attr]
            self._stream.close()  # type: ignore[union-attr]
            self._stream = None

        # sentinel None tells VAD thread to flush remaining buffer and exit
        self._frame_queue.put(None)

        if self._vad_thread is not None:
            self._vad_thread.join(timeout=5.0)
            self._vad_thread = None

        self._state = RecorderState.IDLE
        logger.info("AudioRecorder: flushed and idle")

    # ── internals ─────────────────────────────────────────────────────────────

    def _audio_callback(
        self,
        indata: np.ndarray,
        _frames: int,
        _time: object,
        _status: object,
    ) -> None:
        """sounddevice callback — runs in audio thread. Must be fast."""
        self._frame_queue.put(indata.copy())

    def _vad_loop(self) -> None:
        """Runs in daemon thread. Drains frame_queue, applies VAD, emits phrases."""
        if self._vad_factory is not None:
            vad = self._vad_factory(self._vad_aggressiveness)
        else:
            import webrtcvad  # lazy import

            vad = webrtcvad.Vad(self._vad_aggressiveness)

        speech_frames: list[np.ndarray] = []
        silence_count = 0
        in_speech = False

        while True:
            frame = self._frame_queue.get()

            if frame is None:
                # sentinel — flush whatever we have and exit
                if speech_frames:
                    self._emit(speech_frames)
                break

            # webrtcvad needs int16 PCM bytes
            pcm = (frame.flatten() * 32767).astype(np.int16).tobytes()
            is_speech = vad.is_speech(pcm, self._sample_rate)

            if is_speech:
                speech_frames.append(frame.copy())
                silence_count = 0
                in_speech = True
            else:
                if in_speech:
                    speech_frames.append(frame.copy())  # include trailing silence for context
                    silence_count += 1
                    if silence_count >= _SILENCE_FRAMES_THRESHOLD:
                        if len(speech_frames) >= _MIN_SPEECH_FRAMES:
                            self._emit(speech_frames)
                        speech_frames = []
                        silence_count = 0
                        in_speech = False

    def _emit(self, frames: list[np.ndarray]) -> None:
        """Concatenate frames and fire on_chunk callback."""
        audio = np.concatenate([f.flatten() for f in frames])
        logger.debug("AudioRecorder: emitting phrase chunk (%.2fs)", len(audio) / self._sample_rate)
        self._on_chunk(audio)
