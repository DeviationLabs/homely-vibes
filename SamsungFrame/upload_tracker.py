"""Local file hash tracker for Samsung Frame TV art.

Maintains a JSON file mapping md5_hash -> content_id so we can skip
re-uploading files that already exist on the TV.
"""

import hashlib
import json
from pathlib import Path
from typing import List

from lib.config import get_config
from lib.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = Path("config/samsung_upload_history.json")


def _tracker_path() -> Path:
    cfg = get_config()
    return Path(getattr(cfg.samsung_frame, "upload_history_file", str(_DEFAULT_PATH)))


def _load() -> dict[str, str]:
    path = _tracker_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "file_hashes" in data:
            return dict(data["file_hashes"])
        return dict(data) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read upload history: {e}")
        return {}


def _save(hashes: dict[str, str]) -> None:
    path = _tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"file_hashes": hashes}, indent=2) + "\n")


def file_hash(path: Path) -> str:
    """Compute MD5 hash of file contents."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_known_hashes() -> dict[str, str]:
    """Return {md5_hash: content_id} for previously uploaded files."""
    return _load()


def record_file_hashes(mapping: dict[str, str]) -> None:
    """Record {md5_hash: content_id} for uploaded files."""
    if not mapping:
        return
    hashes = _load()
    hashes.update(mapping)
    _save(hashes)


def remove_ids(content_ids: List[str]) -> None:
    """Remove hash entries pointing to deleted content IDs."""
    if not content_ids:
        return
    id_set = set(content_ids)
    hashes = _load()
    hashes = {h: cid for h, cid in hashes.items() if cid not in id_set}
    _save(hashes)
    logger.debug(f"Removed hashes for {len(content_ids)} deleted IDs")
