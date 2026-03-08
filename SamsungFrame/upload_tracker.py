"""Local upload history tracker for Samsung Frame TV art.

The TV API does not return upload timestamps, so we maintain a local
JSON file mapping content_id -> upload ISO timestamp.  This enables
time-based purge (delete art older than N hours).
"""

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


def _load() -> dict[str, str]:
    path = _tracker_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        uploads: dict[str, str] = data.get("uploads", {})
        return uploads
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read upload history: {e}")
        return {}


def _save(uploads: dict[str, str]) -> None:
    path = _tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"uploads": uploads}, indent=2) + "\n")


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
    uploads = _load()
    for cid in content_ids:
        uploads.pop(cid, None)
    _save(uploads)
    logger.debug(f"Removed {len(content_ids)} IDs from upload history")
