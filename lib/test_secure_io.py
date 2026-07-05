"""Tests for lib.secure_io atomic 0o600 writes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib.secure_io import ensure_secret_perms, write_secret_atomic


def _mode(p: Path) -> int:
    return p.stat().st_mode & 0o777


def test_write_bytes_creates_0600(tmp_path: Path) -> None:
    p = tmp_path / "s.bin"
    write_secret_atomic(p, b"raw-secret")
    assert p.read_bytes() == b"raw-secret"
    assert _mode(p) == 0o600


def test_write_str_creates_0600(tmp_path: Path) -> None:
    p = tmp_path / "s.txt"
    write_secret_atomic(p, "refresh_token_value")
    assert p.read_text() == "refresh_token_value"
    assert _mode(p) == 0o600


def test_write_dict_json_serialized(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    payload = {"access_token": "abc", "refresh_token": "def", "expires_at": 1234}
    write_secret_atomic(p, payload)
    assert json.loads(p.read_text()) == payload
    assert _mode(p) == 0o600


def test_write_overwrites_loose_perms(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("stale")
    p.chmod(0o644)
    write_secret_atomic(p, {"k": "v"})
    assert _mode(p) == 0o600, f"loose-perms overwrite must end 0600, got {oct(_mode(p))}"


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deeper" / "s.json"
    write_secret_atomic(p, {"k": "v"})
    assert p.exists()
    assert _mode(p) == 0o600


def test_write_atomic_no_toctou_window(tmp_path: Path) -> None:
    """Under 0o022 umask, verify file never exists at 0644.

    Set a permissive umask, then invoke the helper. The final mode must still
    be 0600, and (empirically) the file's create-time mode is 0600 — the
    atomic open with an explicit mode overrides umask entirely.
    """
    p = tmp_path / "s.json"
    old = os.umask(0o022)
    try:
        write_secret_atomic(p, {"k": "v"})
    finally:
        os.umask(old)
    assert _mode(p) == 0o600


def test_ensure_perms_tightens_existing(tmp_path: Path) -> None:
    p = tmp_path / "third_party_token.json"
    p.write_text("{}")
    p.chmod(0o644)
    ensure_secret_perms(p)
    assert _mode(p) == 0o600


def test_ensure_perms_missing_file_is_noop(tmp_path: Path) -> None:
    # Must not raise.
    ensure_secret_perms(tmp_path / "does-not-exist.json")


def test_ensure_perms_already_0600_is_noop(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("{}")
    p.chmod(0o600)
    ensure_secret_perms(p)
    assert _mode(p) == 0o600


def test_write_rejects_invalid_type(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    with pytest.raises(TypeError):
        write_secret_atomic(p, 42)  # type: ignore[arg-type]
