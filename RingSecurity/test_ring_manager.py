"""Tests for RingSecurity/ring_manager.py — no patch() on production code.

Ring client is injected via `ring_factory` parameter. Pushover is a real
instance whose HTTP call is replaced with a recorder.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Sequence

import pytest

from lib.config import RingConfig
from lib.MyPushover import Pushover
from RingSecurity.ring_manager import RingAuthError, _save_token, check_devices, notify


class FakeDevice:
    def __init__(self, name: str, battery: int | None, wifi: str | None):
        self.name = name
        self.battery_life = battery
        self.wifi_signal_category = wifi

    async def async_update_health_data(self) -> None:
        return None


class FakeDevices:
    def __init__(self, devs: list[FakeDevice]):
        self.all_devices = devs


class FakeRing:
    def __init__(self, devs: list[FakeDevice]):
        self._devs = devs

    def devices(self) -> FakeDevices:
        return FakeDevices(self._devs)


class RecordingPushover(Pushover):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool:
        self.calls.append({"message": message, "title": title, "priority": priority})
        return True


@pytest.fixture
def cfg(tmp_path: Path) -> RingConfig:
    token_file = tmp_path / "ring_token.json"
    token_file.write_text(json.dumps({"access_token": "fake"}))
    return RingConfig("u", "p", str(token_file), 25)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test-ring")


def _factory(devs: Sequence[FakeDevice]) -> Any:
    async def _make(_session: Any, _token: Any, _tokfile: Any) -> Any:
        return FakeRing(list(devs))

    return _make


async def test_low_battery_and_offline_detected(cfg: RingConfig, logger: logging.Logger) -> None:
    devs = [
        FakeDevice("Front Door", battery=15, wifi="good"),
        FakeDevice("Backyard", battery=90, wifi=None),  # offline
        FakeDevice("Chime", battery=None, wifi="good"),  # wired (None), ignore
        FakeDevice("Floodlight", battery=0, wifi="good"),  # wired (0), ignore
    ]
    low, offline = await check_devices(cfg, logger, ring_factory=_factory(devs))
    assert low == ["Front Door: 15%"]
    assert offline == ["Backyard"]


async def test_all_healthy_no_alerts(cfg: RingConfig, logger: logging.Logger) -> None:
    devs = [FakeDevice("Front Door", battery=90, wifi="good")]
    low, offline = await check_devices(cfg, logger, ring_factory=_factory(devs))
    assert low == []
    assert offline == []


async def test_string_battery_value_coerced(cfg: RingConfig, logger: logging.Logger) -> None:
    devs = [
        FakeDevice("StringLow", battery="15", wifi="good"),  # type: ignore[arg-type]
        FakeDevice("StringHigh", battery="90", wifi="good"),  # type: ignore[arg-type]
        FakeDevice("Garbage", battery="n/a", wifi="good"),  # type: ignore[arg-type]
    ]
    low, offline = await check_devices(cfg, logger, ring_factory=_factory(devs))
    assert low == ["StringLow: 15%"]
    assert offline == []


async def test_health_call_exception_treated_as_offline(
    cfg: RingConfig, logger: logging.Logger
) -> None:
    class ExplodingDevice(FakeDevice):
        async def async_update_health_data(self) -> None:
            raise RuntimeError("boom")

    devs = [ExplodingDevice("Front Door", battery=90, wifi="good")]
    _, offline = await check_devices(cfg, logger, ring_factory=_factory(devs))
    assert offline == ["Front Door"]


async def test_missing_token_raises(tmp_path: Path, logger: logging.Logger) -> None:
    cfg = RingConfig("u", "p", str(tmp_path / "missing.json"), 25)
    with pytest.raises(RingAuthError, match="No Ring token"):
        await check_devices(cfg, logger, ring_factory=_factory([]))


def test_notify_priorities(logger: logging.Logger) -> None:
    p = RecordingPushover()
    notify(p, ["A: 10%"], ["B"], logger)
    assert len(p.calls) == 2
    battery_call = next(c for c in p.calls if "Battery" in (c["title"] or ""))
    offline_call = next(c for c in p.calls if "Offline" in (c["title"] or ""))
    assert battery_call["priority"] == 1
    assert offline_call["priority"] == 0


def test_notify_no_alerts_no_pushover(logger: logging.Logger) -> None:
    p = RecordingPushover()
    notify(p, [], [], logger)
    assert p.calls == []


def test_save_token_chmods_0600(tmp_path: Path) -> None:
    path = tmp_path / "tok.json"
    _save_token(str(path), {"access_token": "secret"})
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, f"token file must be 0600, got {oct(mode)}"
