"""Speech-to-text engine using whisper.cpp via pywhispercpp.

whisper.cpp is a C/C++ inference engine for OpenAI Whisper models that uses
Metal GPU acceleration on Apple Silicon (M-series). pywhispercpp wraps the
C library with Python bindings.

Model is lazy-loaded on first call to transcribe() — startup is instant,
first keystroke takes ~3-5s while the model loads into Metal GPU memory.
Subsequent calls reuse the loaded model with ~400ms latency per phrase.

Model storage: ~/.cache/pywhispercpp/models/ (auto-downloaded on first use)
Recommended model for M2 8GB: large-v3-turbo (~1.6GB, best accuracy)
Fallback for lower memory: medium (~1.5GB) or small (~488MB)
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from lib.config import get_config
from lib.logger import get_logger

cfg = get_config()
logger = get_logger(__name__)


class Transcriber:
    """Lazy-loading whisper.cpp transcriber.

    Thread safety: transcribe() is NOT thread-safe — pywhispercpp model is not
    reentrant. The VoiceNotesApp orchestrator calls it synchronously from the
    VAD thread (one phrase at a time), so no locking is needed.
    """

    def __init__(self) -> None:
        self._model_name: str = cfg.voice_notes.model_id
        self._n_threads: int = cfg.voice_notes.n_threads
        self._model: Optional[object] = None  # pywhispercpp.model.Model

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe float32 16kHz mono audio array. Returns stripped text.

        Returns empty string on silence or if audio is too short.
        """
        if audio.size == 0:
            return ""

        # whisper.cpp needs at least ~0.1s of audio to produce output
        min_samples = int(cfg.voice_notes.sample_rate * 0.1)
        if audio.size < min_samples:
            return ""

        if self._model is None:
            self._load_model()

        segments = self._model.transcribe(audio, n_processors=1)  # type: ignore[union-attr]
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text

    def _load_model(self) -> None:
        """Load whisper.cpp model into Metal GPU memory (~3-5s first time)."""
        from pywhispercpp.model import Model  # type: ignore[import]

        logger.info("Loading whisper.cpp model: %s (%d threads)", self._model_name, self._n_threads)
        # n_threads controls CPU inference fallback; Metal GPU is used automatically on Apple Silicon
        self._model = Model(self._model_name, n_threads=self._n_threads)
        logger.info("Model loaded: %s", self._model_name)
