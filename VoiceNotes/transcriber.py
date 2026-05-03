"""Speech-to-text engine wrapper with parakeet-mlx primary and mlx-whisper fallback.

Model selection:
  cfg.voice_notes.model_backend = "parakeet-mlx"  (default)
    Model: parakeet-tdt-0.6b (~1.2GB fp16, ~0.5s latency on M2)
    Why: fastest on Apple Silicon, built for streaming, excellent accuracy.

  cfg.voice_notes.model_backend = "mlx-whisper"   (fallback)
    Model: mlx-community/whisper-large-v3-turbo-4bit (~400MB 4-bit quant)
    Why: proven accuracy, smaller memory footprint if parakeet unavailable.

Model loading:
  - Lazy: model is loaded on first call to transcribe(), not at import time.
  - Loading takes ~3-5s; callers should show a "Loading model..." UI hint first.
  - After first load, the model stays in memory for the process lifetime.
  - On M2 8GB: parakeet-tdt-0.6b uses ~2-3GB unified memory at runtime.
    Acceptable alongside macOS overhead (~2-3GB), leaves ~2-3GB for other apps.

Usage:
    t = Transcriber()
    text = t.transcribe(audio_chunk)   # numpy float32 array, 16kHz mono
    print(text)
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from lib.config import get_config
from lib.logger import get_logger

# TODO: add parakeet-mlx and mlx-whisper to optional voice deps before uncommenting
# import parakeet_mlx  (parakeet-mlx backend)
# import mlx_whisper   (mlx-whisper backend)

cfg = get_config()
logger = get_logger(__name__)

SUPPORTED_BACKENDS = ("parakeet-mlx", "mlx-whisper")


class Transcriber:
    """Lazy-loading STT engine.

    Implementation plan:
      __init__:
        - Validate cfg.voice_notes.model_backend is in SUPPORTED_BACKENDS.
        - Set self._model = None (lazy load on first transcribe()).
        - Store model_id from cfg.voice_notes.model_id.

      _load_model():
        - Called once from transcribe() when self._model is None.
        - If backend == "parakeet-mlx":
            from parakeet_mlx import from_pretrained
            self._model = from_pretrained(model_id or "parakeet-tdt-0.6b")
        - If backend == "mlx-whisper":
            import mlx_whisper
            self._model = mlx_whisper.load_models.load_model(
                model_id or "mlx-community/whisper-large-v3-turbo-4bit"
            )
        - Log model name and approx size hint.

      transcribe(audio: np.ndarray) -> str:
        - If _model is None, call _load_model().
        - Validate: audio must be float32, 1D or 2D mono, non-empty.
        - Flatten to 1D if 2D.
        - Dispatch to _transcribe_parakeet or _transcribe_whisper.
        - Strip leading/trailing whitespace from result.
        - Return empty string (not None) on silence/no-speech detection.

      _transcribe_parakeet(audio: np.ndarray) -> str:
        - Call self._model.transcribe(audio, sample_rate=16000).
        - Return result.text or "".

      _transcribe_whisper(audio: np.ndarray) -> str:
        - Call mlx_whisper.transcribe(audio, path_or_hf_repo=model_id).
        - Return result["text"] or "".
    """

    def __init__(self) -> None:
        backend = cfg.voice_notes.model_backend
        if backend not in SUPPORTED_BACKENDS:
            raise ValueError(f"model_backend must be one of {SUPPORTED_BACKENDS}, got {backend!r}")
        self._backend: str = backend
        self._model_id: str = cfg.voice_notes.model_id
        self._model: Optional[object] = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, _audio: np.ndarray) -> str:
        """Transcribe a numpy float32 audio chunk (16kHz mono) to text.

        Returns empty string on silence. Never raises on empty/short audio.

        TODO: implement per class docstring plan (rename _audio → audio).
        """
        if self._model is None:
            self._load_model()
        # TODO: validate, dispatch, return
        return ""

    def _load_model(self) -> None:
        """Load STT model into memory. Called once lazily.

        TODO: implement per class docstring plan.
        """
        logger.info("Loading STT model: backend=%s model_id=%s", self._backend, self._model_id)
        # TODO: implement
