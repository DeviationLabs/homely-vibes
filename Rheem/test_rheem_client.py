#!/usr/bin/env python3
"""Tests for Rheem EcoNet client and monitor.

No patch() — dependencies (EcoNet api, Pushover) are injected as fakes.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest
from pyeconet.equipment import EquipmentType
from pyeconet.errors import GenericHTTPError, InvalidCredentialsError

from Rheem.rheem_client import RheemAPIError, RheemAuthError, RheemClient
from Rheem.rheem_manager import RheemMonitor


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


@dataclass
class FakeWaterHeater:
    serial_number: str
    name: str
    availability: Optional[int]
    running: bool = False
    set_point: int = 120
    connected: bool = True

    @property
    def device_name(self) -> str:
        return self.name

    @property
    def tank_hot_water_availability(self) -> Optional[int]:
        return self.availability


class FakeEcoNetApi:
    def __init__(self, heaters: list[FakeWaterHeater]) -> None:
        self._heaters = heaters

    async def get_equipment_by_type(
        self, equipment_types: list[EquipmentType]
    ) -> dict[EquipmentType, list[FakeWaterHeater]]:
        result: dict[EquipmentType, list[FakeWaterHeater]] = {}
        for et in equipment_types:
            result[et] = list(self._heaters) if et == EquipmentType.WATER_HEATER else []
        return result


class FakePushover:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int]] = []

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool:
        self.sent.append((message, title or "", priority))
        return True


# --------------------------------------------------------------------------- #
# RheemClient tests
# --------------------------------------------------------------------------- #


def _client_with(heaters: list[FakeWaterHeater]) -> RheemClient:
    api = FakeEcoNetApi(heaters)

    async def factory() -> FakeEcoNetApi:
        return api

    return RheemClient("u@example.com", "pw", api_factory=factory)


def test_get_water_heaters_maps_availability() -> None:
    heaters = [
        FakeWaterHeater(serial_number="S1", name="Garage", availability=66),
        FakeWaterHeater(serial_number="S2", name="Basement", availability=None),
    ]
    client = _client_with(heaters)
    statuses = asyncio.run(client.get_water_heaters())
    assert len(statuses) == 2
    s1, s2 = statuses
    assert s1.serial_number == "S1"
    assert s1.name == "Garage"
    assert s1.availability == 66
    assert s1.running is False
    assert s1.set_point == 120
    assert s1.connected is True
    assert s2.availability is None


def test_get_water_heaters_auth_error() -> None:
    async def factory() -> FakeEcoNetApi:
        raise InvalidCredentialsError("bad creds")

    client = RheemClient("u@example.com", "pw", api_factory=factory)
    with pytest.raises(RheemAuthError):
        asyncio.run(client.get_water_heaters())


def test_get_water_heaters_api_error() -> None:
    async def factory() -> FakeEcoNetApi:
        raise GenericHTTPError(500)

    client = RheemClient("u@example.com", "pw", api_factory=factory)
    with pytest.raises(RheemAPIError):
        asyncio.run(client.get_water_heaters())


# --------------------------------------------------------------------------- #
# RheemMonitor tests
# --------------------------------------------------------------------------- #


def _monitor_with(
    heaters: list[FakeWaterHeater],
    state_file: str,
    low_threshold: int = 33,
    mid_threshold: int = 66,
) -> tuple[RheemMonitor, FakePushover]:
    client = _client_with(heaters)
    pushover = FakePushover()
    logger = logging.getLogger("test_rheem")
    monitor = RheemMonitor(
        client=client,
        pushover=pushover,
        logger=logger,
        state_file=state_file,
        low_threshold=low_threshold,
        mid_threshold=mid_threshold,
    )
    return monitor, pushover


def test_low_availability_fires_p1_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)], state
    )
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    msg, title, priority = pushover.sent[0]
    assert title == "Rheem Low Hot Water"
    assert priority == 1
    assert "Garage" in msg
    assert monitor.alerted["S1"] is True


def test_empty_tank_fires_p1_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=0)], state
    )
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert pushover.sent[0][2] == 1
    assert monitor.alerted["S1"] is True


def test_already_alerted_no_duplicate(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    # Still low -> no second alert.
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] is True


def test_recovery_to_mid_clears_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert monitor.alerted["S1"] is True
    # Recover to mid.
    heaters[0].availability = 66
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 2
    msg, title, priority = pushover.sent[1]
    assert title == "Rheem Hot Water Recovered"
    assert priority == -1
    assert monitor.alerted["S1"] is False


def test_full_tank_no_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=100)], state
    )
    asyncio.run(monitor.check_once())
    assert pushover.sent == []
    assert monitor.alerted == {}


def test_none_availability_skipped(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=None)], state
    )
    asyncio.run(monitor.check_once())
    assert pushover.sent == []
    assert monitor.alerted == {}


def test_disconnected_skipped(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=0, connected=False)],
        state,
    )
    asyncio.run(monitor.check_once())
    assert pushover.sent == []
    assert monitor.alerted == {}


def test_state_persisted_across_instances(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, _ = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert monitor.alerted["S1"] is True
    # New monitor instance loads persisted state.
    monitor2, pushover2 = _monitor_with(heaters, state)
    assert monitor2.alerted["S1"] is True
    # Still low -> no re-alert (state was loaded).
    asyncio.run(monitor2.check_once())
    assert len(pushover2.sent) == 0


def test_pruned_gone_device(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, _ = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert "S1" in monitor.alerted
    # Device disappears.
    monitor, _ = _monitor_with([], state)
    asyncio.run(monitor.check_once())
    assert "S1" not in monitor.alerted


def test_multiple_heaters_independent(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [
        FakeWaterHeater(serial_number="S1", name="Garage", availability=33),
        FakeWaterHeater(serial_number="S2", name="Basement", availability=100),
    ]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert monitor.alerted["S1"] is True
    assert monitor.alerted.get("S2", False) is False
    assert len(pushover.sent) == 1
