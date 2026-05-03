"""Per-session markdown file writer with real-time streaming append.

Output format:
  ~/bin/knowledge/notes/YYYY-MM-DDThh-mm.md

  ## 2026-05-03 14:22
  Hello world this is my first transcription.
  And here is more text as the next chunk came in.

  ---

Each recording session gets one file. The header is written on open().
Text is appended incrementally as STT chunks arrive (real-time).
The trailing `---` separator is written on close() to mark session end.

The notes directory is created automatically on first open if it doesn't exist.

Usage:
    writer = SessionWriter()
    writer.open()          # creates file, writes header
    writer.append("text")  # appends text in real-time (line-buffered)
    writer.append(" more") # can be called multiple times per session
    writer.close()         # writes trailing separator
    print(writer.path)     # ~/bin/knowledge/notes/2026-05-03T14-22.md
"""

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

    Implementation plan:
      __init__:
        - Resolve notes_dir from cfg.voice_notes.notes_dir (expand ~).
        - Set self._path = None, self._file = None.
        - self._session_start: Optional[datetime] = None.

      open() -> Path:
        - Create notes_dir if it doesn't exist (parents=True, exist_ok=True).
        - Compute filename: datetime.now().strftime("%Y-%m-%dT%H-%M") + ".md".
        - Open file in write mode with line buffering (buffering=1).
        - Write header: f"## {datetime.now().strftime('%Y-%m-%d %H:%M')}\n".
        - Return the resolved Path.

      append(text: str) -> None:
        - Guard: if file not open, log warning and return.
        - Write text directly to file (no trailing newline added — caller
          controls chunking; STT results may be mid-sentence).
        - Flush after each append so file is readable in real-time by any
          watcher (e.g. VSCode sidebar, tail -f).

      close() -> None:
        - Write "\n\n---\n" separator.
        - Close file handle.
        - Log path and word count for the session.
        - Reset self._file = None, self._path = None.

      @property path -> Optional[Path]:
        - Return current session file path or None if not open.
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
        """Create session file and write header. Returns the file path.

        TODO: implement per class docstring plan.
        """
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._session_start = datetime.now()
        filename = self._session_start.strftime("%Y-%m-%dT%H-%M") + ".md"
        self._path = self._notes_dir / filename
        logger.info("SessionWriter.open: %s", self._path)
        # TODO: open file, write header
        return self._path

    def append(self, text: str) -> None:
        """Append transcribed text to the session file (line-buffered).

        TODO: implement per class docstring plan.
        """
        if self._file is None:
            logger.warning("SessionWriter.append called but file is not open")
            return
        # TODO: write text and flush

    def close(self) -> None:
        """Write closing separator and close the file handle.

        TODO: implement per class docstring plan.
        """
        if self._file is None:
            return
        logger.info("SessionWriter.close: %s", self._path)
        # TODO: write separator, close, log word count
        self._file = None
        self._path = None
