"""Tests for RingBeams/beams_manager.py — no patch() on production code.

Sidecar subprocess is not spawned in unit tests; classify() and notify() are
exercised directly with DeviceRecord fixtures. Auth-error path tested via
missing-token file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from lib.config import RingBeamsConfig
from lib.MyPushover import Pushover
from RingBeams.beams_manager import (
    BeamsAuthError,
    DeviceRecord,
    classify,
    notify,
    run_sidecar,
)


class RecordingPushover(Pushover):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool:
        self.calls.append({"message": message, "title": title, "priority": priority})
        return True


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test-beams")


def _rec(
    name: str,
    battery: int | None = None,
    battery_status: str | None = None,
    tamper: str | None = "ok",
) -> DeviceRecord:
    return DeviceRecord(
        name=name,
        device_type="sensor.motion",
        location="Home",
        battery=battery,
        battery_status=battery_status,
        tamper=tamper,
    )


def test_low_battery_threshold_only() -> None:
    devs = [
        _rec("Mailbox", battery=12, battery_status="warn"),
        _rec("Motion Kitchen", battery=0, battery_status="warn"),
        _rec("Motion Corridor", battery=25, battery_status="ok"),  # at threshold, skip
        _rec("Motion Entrance", battery=65, battery_status="ok"),
    ]
    low, tamper = classify(devs, threshold_pct=25)
    assert low == ["Mailbox: 12%", "Motion Kitchen: 0%"]
    assert tamper == []


def test_ring_warn_status_triggers_even_if_above_threshold() -> None:
    # Ring says "warn" — trust it even if numeric value contradicts.
    devs = [_rec("Weird", battery=80, battery_status="warn")]
    low, tamper = classify(devs, threshold_pct=25)
    assert low == ["Weird: 80%"]
    assert tamper == []


def test_wired_devices_skipped() -> None:
    devs = [
        _rec("Base Station", battery=None, battery_status="charged"),
        _rec("Keypad", battery=100, battery_status="charging"),
        _rec("Adapter", battery=None, battery_status="none"),
        _rec("Motion Kitchen", battery=0, battery_status="warn"),
    ]
    low, _ = classify(devs, threshold_pct=25)
    assert low == ["Motion Kitchen: 0%"]  # only the real one


def test_tamper_detected() -> None:
    devs = [
        _rec("Door", battery=99, battery_status="full", tamper="tamper"),
        _rec("Motion", battery=80, battery_status="ok", tamper="ok"),
    ]
    low, tamper = classify(devs, threshold_pct=25)
    assert low == []
    assert tamper == ["Door (tampered)"]


def test_notify_priorities(logger: logging.Logger) -> None:
    p = RecordingPushover()
    notify(p, ["A: 10%"], ["B (tampered)"], [], logger)
    assert len(p.calls) == 2
    battery = next(c for c in p.calls if "Battery" in (c["title"] or ""))
    tamper = next(c for c in p.calls if "Tamper" in (c["title"] or ""))
    assert battery["priority"] == 1
    assert tamper["priority"] == 0


def test_notify_partial_failure_alerts_p1(logger: logging.Logger) -> None:
    """Sidecar partial-location failure MUST alert even when devices returned
    look healthy — otherwise the user sees false 'all healthy' with missing
    devices."""
    p = RecordingPushover()
    notify(p, [], [], ["getDevices(Home): connection reset"], logger)
    assert len(p.calls) == 1
    assert "Partial" in (p.calls[0]["title"] or "")
    assert p.calls[0]["priority"] == 1
    assert "connection reset" in p.calls[0]["message"]


def test_notify_no_alerts_silent(logger: logging.Logger) -> None:
    p = RecordingPushover()
    notify(p, [], [], [], logger)
    assert p.calls == []


def test_missing_token_raises_auth_error(tmp_path: Path, logger: logging.Logger) -> None:
    cfg = RingBeamsConfig(
        token_file=str(tmp_path / "missing.json"),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    with pytest.raises(BeamsAuthError, match="No Ring token"):
        run_sidecar(cfg, logger)


def test_sidecar_auth_failure_exit5_treated_as_auth(tmp_path: Path, logger: logging.Logger) -> None:
    """Sidecar exit=5 with JSON error is the auth/list-locations failure class."""
    tok = tmp_path / "tok.json"
    tok.write_text('{"refresh_token": "fake"}')
    script = tmp_path / "fake_sidecar.js"
    # Not a real node file — we pass /bin/sh and pretend it's node.
    fake = tmp_path / "fake.sh"
    fake.write_text('#!/bin/sh\necho \'{"error":"bad token"}\' >&2\nexit 5\n')
    fake.chmod(0o755)
    cfg = RingBeamsConfig(
        token_file=str(tok),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    with pytest.raises(BeamsAuthError, match="bad token"):
        run_sidecar(cfg, logger, node_path=str(fake), script_path=str(script))


def test_sidecar_exit1_node_crash_not_auth(tmp_path: Path, logger: logging.Logger) -> None:
    """Node crash-at-load (exit=1 with raw stack, no JSON envelope) MUST route
    to RuntimeError, not BeamsAuthError. This is the prod-host 2026-07-04 case:
    undici + Node 18 ReferenceError got misclassified as "Auth Required"."""
    tok = tmp_path / "tok.json"
    tok.write_text('{"refresh_token": "fake"}')
    fake = tmp_path / "fake.sh"
    # Raw stack trace on stderr, no {"error": "..."} envelope, exit 1.
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'ReferenceError: File is not defined' >&2\n"
        "echo '    at Object.<anonymous>' >&2\n"
        "exit 1\n"
    )
    fake.chmod(0o755)
    cfg = RingBeamsConfig(
        token_file=str(tok),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    with pytest.raises(RuntimeError, match="sidecar exit=1") as exc:
        run_sidecar(cfg, logger, node_path=str(fake), script_path=str(tmp_path / "x.js"))
    assert not isinstance(exc.value, BeamsAuthError)


def test_sidecar_generic_error_not_misclassified_as_auth(
    tmp_path: Path, logger: logging.Logger
) -> None:
    """rc=4 (post-auth unhandled) MUST NOT map to BeamsAuthError — otherwise a
    parsing bug in the sidecar would tell the user to re-auth."""
    tok = tmp_path / "tok.json"
    tok.write_text('{"refresh_token": "fake"}')
    fake = tmp_path / "fake.sh"
    fake.write_text('#!/bin/sh\necho \'{"error":"unhandled: bad device"}\' >&2\nexit 4\n')
    fake.chmod(0o755)
    cfg = RingBeamsConfig(
        token_file=str(tok),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    with pytest.raises(RuntimeError, match="sidecar exit=4") as exc:
        run_sidecar(cfg, logger, node_path=str(fake), script_path=str(tmp_path / "x.js"))
    # Explicitly assert it's NOT the auth subclass.
    assert not isinstance(exc.value, BeamsAuthError)


def test_sidecar_happy_path(tmp_path: Path, logger: logging.Logger) -> None:
    """Fake sidecar prints a valid device list; run_sidecar parses it."""
    tok = tmp_path / "tok.json"
    tok.write_text('{"refresh_token": "fake"}')
    fake = tmp_path / "fake.sh"
    fake.write_text(
        "#!/bin/sh\ncat <<EOF\n"
        '{"devices":[{"name":"Mailbox","deviceType":"motion-sensor.beams",'
        '"batteryLevel":12,"batteryStatus":"warn","tamperStatus":"ok",'
        '"locationName":"Home"}]}\nEOF\n'
    )
    fake.chmod(0o755)
    cfg = RingBeamsConfig(
        token_file=str(tok),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    devs, errs = run_sidecar(cfg, logger, node_path=str(fake), script_path=str(tmp_path / "x.js"))
    assert len(devs) == 1
    assert devs[0].name == "Mailbox"
    assert devs[0].battery == 12
    assert devs[0].battery_status == "warn"
    assert errs == []


def test_sidecar_surfaces_partial_errors(tmp_path: Path, logger: logging.Logger) -> None:
    """Sidecar returned devices AND per-location errors — both surface."""
    tok = tmp_path / "tok.json"
    tok.write_text('{"refresh_token": "fake"}')
    fake = tmp_path / "fake.sh"
    fake.write_text(
        "#!/bin/sh\ncat <<EOF\n"
        '{"devices":[{"name":"Mailbox","batteryLevel":90,"batteryStatus":"ok",'
        '"tamperStatus":"ok"}],'
        '"errors":["getDevices(Second Home): oops"]}\nEOF\n'
    )
    fake.chmod(0o755)
    cfg = RingBeamsConfig(
        token_file=str(tok),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    devs, errs = run_sidecar(cfg, logger, node_path=str(fake), script_path=str(tmp_path / "x.js"))
    assert len(devs) == 1
    assert errs == ["getDevices(Second Home): oops"]


def test_sidecar_token_write_warn_on_stderr_is_logged_not_raised(
    tmp_path: Path, logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """Sidecar exit=0 with a TOKEN_WRITE_FAILED warn on stderr: parse normally
    and log the warning. Regression guard for the 2026-07-05 invalid_grant
    scenario — the ring-client-api rotates refresh_token; if our write fails
    silently, the next RingSecurity run gets invalid_grant. Surfacing the
    warn line lets us diagnose the chain."""
    tok = tmp_path / "tok.json"
    tok.write_text('{"refresh_token": "fake"}')
    fake = tmp_path / "fake.sh"
    fake.write_text(
        "#!/bin/sh\n"
        'echo \'{"warn":"TOKEN_WRITE_FAILED: EACCES","path":"/tmp/tok"}\' >&2\n'
        "cat <<EOF\n"
        '{"devices":[{"name":"Mailbox","batteryLevel":90,"batteryStatus":"ok",'
        '"tamperStatus":"ok"}]}\nEOF\n'
    )
    fake.chmod(0o755)
    cfg = RingBeamsConfig(
        token_file=str(tok),
        battery_threshold_pct=25,
        sidecar_timeout_seconds=5,
    )
    with caplog.at_level(logging.WARNING):
        devs, errs = run_sidecar(
            cfg, logger, node_path=str(fake), script_path=str(tmp_path / "x.js")
        )
    assert len(devs) == 1
    assert errs == []
    assert any("TOKEN_WRITE_FAILED" in r.message for r in caplog.records)
