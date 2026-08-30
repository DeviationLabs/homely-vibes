"""Per-session markdown file writer with real-time streaming append."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.config import get_config
from lib.logger import get_logger

cfg = get_config()
logger = get_logger(__name__)


class SessionWriter:
    """Real-time streaming writer for per-session voice note files.

    Opens ~/bin/knowledge/notes/YYYY-MM-DDThh-mm.md on open(), appends
    transcription chunks immediately (line-buffered), closes with a --- separator.
    """

    def __init__(self) -> None:
        self._notes_dir = Path(cfg.voice_notes.notes_dir).expanduser()
        self._path: Optional[Path] = None
        self._file: Optional[io.TextIOWrapper] = None
        self._session_start: Optional[datetime] = None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._file is not None

    def open(self) -> Path:
        """Create session file and write timestamp header."""
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._session_start = datetime.now()
        filename = self._session_start.strftime("%Y-%m-%dT%H-%M") + ".md"
        self._path = self._notes_dir / filename
        # buffering=1 = line-buffered so tail -f / VSCode picks up each append instantly
        self._file = self._path.open("w", buffering=1, encoding="utf-8")
        self._file.write(f"## {self._session_start.strftime('%Y-%m-%d %H:%M')}\n")
        self._file.flush()
        logger.info("SessionWriter opened: %s", self._path)
        return self._path

    def append(self, text: str) -> None:
        """Append transcribed text chunk. Called repeatedly while recording."""
        if self._file is None:
            logger.warning("SessionWriter.append called before open()")
            return
        self._file.write(text)
        self._file.flush()

    def close(self) -> None:
        """Write closing separator and flush."""
        if self._file is None:
            return
        self._file.write("\n\n---\n")
        self._file.flush()
        self._file.close()
        logger.info("SessionWriter closed: %s", self._path)
        self._file = None
        self._path = None
        self._session_start = None
