"""Tests for lib.file_lock — POSIX advisory flock for cross-process serialization.

Uses real subprocesses (no patch()) to exercise actual flock semantics — a
mocked flock would let the tests pass even if the real primitive was wrong.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib.file_lock import LockTimeoutError, acquire_lock


def test_lock_creates_sibling_lockfile(tmp_path: Path) -> None:
    resource = tmp_path / "token.json"
    with acquire_lock(resource):
        assert (tmp_path / "token.json.lock").exists()


def test_lock_released_after_context_exit(tmp_path: Path) -> None:
    resource = tmp_path / "token.json"
    with acquire_lock(resource, timeout_s=1.0):
        pass
    # A second acquire should succeed immediately.
    with acquire_lock(resource, timeout_s=1.0):
        pass


def test_lock_released_after_exception(tmp_path: Path) -> None:
    resource = tmp_path / "token.json"
    with pytest.raises(RuntimeError, match="boom"):
        with acquire_lock(resource, timeout_s=1.0):
            raise RuntimeError("boom")
    # Lock must be released even after exception.
    with acquire_lock(resource, timeout_s=1.0):
        pass


def test_second_holder_times_out(tmp_path: Path) -> None:
    """A second process holding the lock blocks us; we time out cleanly."""
    resource = tmp_path / "token.json"
    holder_script = tmp_path / "holder.py"
    holder_script.write_text(
        "import sys, time\n"
        "sys.path.insert(0, '" + str(Path(__file__).resolve().parent.parent) + "')\n"
        "from lib.file_lock import acquire_lock\n"
        f"with acquire_lock('{resource}', timeout_s=5.0):\n"
        "    print('ACQUIRED', flush=True)\n"
        "    time.sleep(3)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, str(holder_script)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        # Wait for the holder to acquire.
        assert holder.stdout is not None
        line = holder.stdout.readline().strip()
        assert line == "ACQUIRED", f"unexpected holder output: {line!r}"

        start = time.monotonic()
        with pytest.raises(LockTimeoutError):
            with acquire_lock(resource, timeout_s=0.5, poll_interval_s=0.05):
                pass
        elapsed = time.monotonic() - start
        # Should time out roughly at the timeout, not block forever.
        assert 0.4 < elapsed < 2.0, f"timeout deviated: {elapsed:.2f}s"
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_lock_released_when_holder_crashes(tmp_path: Path) -> None:
    """POSIX flock auto-releases on process exit including SIGKILL — this is
    why we use it instead of a PID sentinel. Regression guard for that
    guarantee (would fail on any switch to mkdir/pidfile without cleanup)."""
    resource = tmp_path / "token.json"
    holder_script = tmp_path / "holder.py"
    holder_script.write_text(
        "import sys, time\n"
        "sys.path.insert(0, '" + str(Path(__file__).resolve().parent.parent) + "')\n"
        "from lib.file_lock import acquire_lock\n"
        f"with acquire_lock('{resource}'):\n"
        "    print('ACQUIRED', flush=True)\n"
        "    time.sleep(60)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, str(holder_script)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ACQUIRED"
        holder.kill()
        holder.wait(timeout=5)
        # Now we should be able to acquire quickly.
        with acquire_lock(resource, timeout_s=2.0):
            pass
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5)
