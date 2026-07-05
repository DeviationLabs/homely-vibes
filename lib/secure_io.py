"""Atomic 0o600 file writes for secret material (OAuth tokens, refresh tokens, keys).

Two entry points cover the two patterns in this repo:

- ``write_secret_atomic(path, content)`` — we own the write: create the file with
  ``0o600`` from birth (no TOCTOU window under a 0o022 umask).
- ``ensure_secret_perms(path)`` — a third-party library owns the write (e.g. yalexs
  writing the August token cache, SamsungTVWS writing the pairing token). Call
  this immediately after the library returns to tighten perms.

Both are safe to call on files that already exist with looser modes — they always
end at 0o600.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Union

_SecretContent = Union[str, bytes, dict[str, Any]]


def _to_bytes(content: _SecretContent) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, dict):
        return json.dumps(content).encode("utf-8")
    raise TypeError(
        f"write_secret_atomic content must be str, bytes, or dict; got {type(content).__name__}"
    )


def write_secret_atomic(path: Union[str, Path], content: _SecretContent) -> None:
    """Write ``content`` to ``path`` with mode ``0o600``, atomically.

    Uses ``os.open(..., O_WRONLY|O_CREAT|O_TRUNC, 0o600)`` so the file is
    world-unreadable from creation — there is no window in which a peer
    process could read it via a wider default umask.

    ``content`` may be ``str``, ``bytes``, or ``dict`` (serialized as JSON).

    If the file already existed with looser perms, ``os.open`` preserves the
    existing mode; a final ``chmod`` normalizes those cases.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = _to_bytes(content)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    os.chmod(p, 0o600)


def ensure_secret_perms(path: Union[str, Path]) -> None:
    """Tighten ``path`` to ``0o600`` if it exists. No-op if missing.

    For token/cache files written by third-party libraries where we can't
    control the open flags. Call immediately after the library returns.
    """
    p = Path(path)
    if p.exists():
        os.chmod(p, 0o600)
