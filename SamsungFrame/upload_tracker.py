"""Local upload history tracker for Samsung Frame TV art.

The TV API does not return upload timestamps, so we maintain a local
JSON file mapping content_id -> upload ISO timestamp.  This enables
time-based purge (delete art older than N hours).
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from lib.config import get_config
from lib.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = Path("config/samsung_upload_history.json")


def _tracker_path() -> Path:
    cfg = get_config()
    return Path(getattr(cfg.samsung_frame, "upload_history_file", str(_DEFAULT_PATH)))


def _load_full() -> dict[str, dict[str, str]]:
    path = _tracker_path()
    if not path.exists():
        return {"uploads": {}, "file_hashes": {}}
    try:
        data = json.loads(path.read_text())
        return {
            "uploads": data.get("uploads", {}),
            "file_hashes": data.get("file_hashes", {}),
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read upload history: {e}")
        return {"uploads": {}, "file_hashes": {}}


def _load() -> dict[str, str]:
    return _load_full()["uploads"]


def _save_full(data: dict[str, dict[str, str]]) -> None:
    path = _tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _save(uploads: dict[str, str]) -> None:
    full = _load_full()
    full["uploads"] = uploads
    _save_full(full)


def record_uploads(content_ids: List[str]) -> None:
    """Record current timestamp for each uploaded content ID."""
    if not content_ids:
        return
    uploads = _load()
    now = datetime.now(timezone.utc).isoformat()
    for cid in content_ids:
        uploads[cid] = now
    _save(uploads)
    logger.info(f"Recorded {len(content_ids)} uploads in history")


def get_stale_ids(art_ids: List[str], max_age_hours: int = 24) -> List[str]:
    """Return IDs from art_ids that are older than max_age_hours or unknown.

    An ID is stale if:
    - It has no entry in the tracker (uploaded before tracking started)
    - Its recorded timestamp is older than max_age_hours
    """
    uploads = _load()
    now = datetime.now(timezone.utc)
    stale: List[str] = []

    for cid in art_ids:
        ts_str = uploads.get(cid)
        if not ts_str:
            stale.append(cid)
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            age_hours = (now - ts).total_seconds() / 3600
            if age_hours > max_age_hours:
                stale.append(cid)
        except ValueError:
            stale.append(cid)

    return stale


def remove_ids(content_ids: List[str]) -> None:
    """Remove deleted content IDs from tracker."""
    if not content_ids:
        return
    full = _load_full()
    for cid in content_ids:
        full["uploads"].pop(cid, None)
    removed_hashes = [h for h, cid in full["file_hashes"].items() if cid in content_ids]
    for h in removed_hashes:
        del full["file_hashes"][h]
    _save_full(full)
    logger.debug(f"Removed {len(content_ids)} IDs from upload history")


def file_hash(path: Path) -> str:
    """Compute MD5 hash of file contents."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_known_hashes() -> dict[str, str]:
    """Return {md5_hash: content_id} for previously uploaded files."""
    return _load_full()["file_hashes"]


def record_file_hashes(mapping: dict[str, str]) -> None:
    """Record {md5_hash: content_id} for uploaded files."""
    if not mapping:
        return
    full = _load_full()
    full["file_hashes"].update(mapping)
    _save_full(full)
