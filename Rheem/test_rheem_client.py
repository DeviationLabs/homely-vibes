#!/usr/bin/env python3
"""Tests for Rheem EcoNet client and monitor.

No patch() — dependencies (EcoNet api, Pushover) are injected as fakes.
"""

import asyncio
import json
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
# RheemMonitor tests — three-tier (P2 empty / P1 low / clear at mid)
# --------------------------------------------------------------------------- #


def _monitor_with(
    heaters: list[FakeWaterHeater],
    state_file: str,
    empty_threshold: int = 0,
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
        empty_threshold=empty_threshold,
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
    assert "setpoint 120°F" in msg
    assert monitor.alerted["S1"] == "p1"


def test_empty_tank_fires_p2_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=0)], state
    )
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    msg, title, priority = pushover.sent[0]
    assert title == "Rheem Hot Water Empty"
    assert priority == 2
    assert "setpoint 120°F" in msg
    assert monitor.alerted["S1"] == "p2"


def test_already_alerted_no_duplicate(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    # Still low -> no second alert.
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p1"


def test_escalation_low_to_empty_fires_p2(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # P1
    assert monitor.alerted["S1"] == "p1"
    # Drops to empty -> escalate to P2.
    heaters[0].availability = 0
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 2
    msg, title, priority = pushover.sent[1]
    assert title == "Rheem Hot Water Empty"
    assert priority == 2
    assert monitor.alerted["S1"] == "p2"


def test_de_escalation_empty_to_low_no_realert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=0)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # P2
    assert monitor.alerted["S1"] == "p2"
    # Recovers to 1/3rd (still in low zone) -> no re-alert, tier stays p2.
    heaters[0].availability = 33
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p2"


def test_recovery_to_mid_clears_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert monitor.alerted["S1"] == "p1"
    # Recover to mid.
    heaters[0].availability = 66
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 2
    msg, title, priority = pushover.sent[1]
    assert title == "Rheem Hot Water Recovered"
    assert priority == -1
    assert "setpoint 120°F" in msg
    assert "S1" not in monitor.alerted


def test_recovery_from_empty_clears_alert(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=0)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # P2
    # Jump straight to full -> clear.
    heaters[0].availability = 100
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 2
    assert pushover.sent[1][2] == -1
    assert "S1" not in monitor.alerted


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
    assert monitor.alerted["S1"] == "p1"
    # New monitor instance loads persisted state.
    monitor2, pushover2 = _monitor_with(heaters, state)
    assert monitor2.alerted["S1"] == "p1"
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


def test_none_setpoint_shows_unknown(tmp_path: Path) -> None:
    """A heater that doesn't report a setpoint shows 'unknown' in the alert."""
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=33, set_point=None)], state
    )
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    msg, _, _ = pushover.sent[0]
    assert "setpoint unknown" in msg


def test_setpoint_raised_suppresses_new_alert(tmp_path: Path) -> None:
    """Setpoint raised since last check suppresses a new low alert.

    The tank reports less hot water because it's reheating to the new higher
    target, not because of an actual shortage — don't alert.
    """
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=120)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # baseline: full, no alert
    assert pushover.sent == []
    # Setpoint raised and availability drops to low.
    heaters[0].set_point = 140
    heaters[0].availability = 33
    asyncio.run(monitor.check_once())
    assert pushover.sent == []  # suppressed
    assert "S1" not in monitor.alerted


def test_setpoint_raised_suppresses_escalation(tmp_path: Path) -> None:
    """Setpoint raised while already in P1 suppresses P2 escalation."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33, set_point=120)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # P1 fired
    assert monitor.alerted["S1"] == "p1"
    assert len(pushover.sent) == 1
    # Setpoint raised and availability drops to empty.
    heaters[0].set_point = 140
    heaters[0].availability = 0
    asyncio.run(monitor.check_once())
    # Escalation suppressed; still only the original P1.
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p1"


def test_setpoint_unchanged_still_alerts(tmp_path: Path) -> None:
    """No setpoint raise -> alert fires normally (regression guard)."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=120)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # baseline
    # Same setpoint, availability drops to low.
    heaters[0].availability = 33
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p1"


def test_setpoint_lowered_still_alerts(tmp_path: Path) -> None:
    """Setpoint lowered does not suppress (drop is not caused by reheating)."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=140)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # baseline
    heaters[0].set_point = 120
    heaters[0].availability = 33
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p1"


def test_setpoint_raised_then_unchanged_fires_alert(tmp_path: Path) -> None:
    """Suppression is one-cycle only; if still low next check, alert fires."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=120)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # baseline
    # Setpoint raised, availability drops.
    heaters[0].set_point = 140
    heaters[0].availability = 33
    asyncio.run(monitor.check_once())  # suppressed
    assert pushover.sent == []
    # Next cycle: setpoint unchanged, still low -> alert fires.
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p1"


def test_none_setpoint_never_suppresses(tmp_path: Path) -> None:
    """A tank that doesn't report setpoint can never trigger suppression."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=None)]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())  # baseline
    heaters[0].availability = 33
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 1
    assert monitor.alerted["S1"] == "p1"


def test_setpoint_persisted_across_instances(tmp_path: Path) -> None:
    """Setpoint tracking survives restart (persisted in state file)."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=120)]
    monitor, _ = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert monitor.setpoints["S1"] == 120
    # New instance loads persisted setpoint.
    monitor2, pushover2 = _monitor_with(heaters, state)
    assert monitor2.setpoints["S1"] == 120
    # Raise setpoint + drop availability -> suppressed (previous setpoint known).
    heaters[0].set_point = 140
    heaters[0].availability = 33
    asyncio.run(monitor2.check_once())
    assert pushover2.sent == []


def test_setpoints_pruned_with_gone_device(tmp_path: Path) -> None:
    """Setpoint entry is pruned when a device disappears."""
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=100, set_point=120)]
    monitor, _ = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert "S1" in monitor.setpoints
    monitor, _ = _monitor_with([], state)
    asyncio.run(monitor.check_once())
    assert "S1" not in monitor.setpoints


def test_multiple_heaters_independent(tmp_path: Path) -> None:
    state = str(tmp_path / "state.json")
    heaters = [
        FakeWaterHeater(serial_number="S1", name="Garage", availability=33),
        FakeWaterHeater(serial_number="S2", name="Basement", availability=0),
    ]
    monitor, pushover = _monitor_with(heaters, state)
    asyncio.run(monitor.check_once())
    assert monitor.alerted["S1"] == "p1"
    assert monitor.alerted["S2"] == "p2"
    # One P1 + one P2.
    priorities = sorted(p for _, _, p in pushover.sent)
    assert priorities == [1, 2]


# --------------------------------------------------------------------------- #
# Resilience: transient errors must not kill the monitor loop
# --------------------------------------------------------------------------- #


class ThrowingEcoNetApi:
    """Fake api whose get_equipment_by_type raises a non-PyeconetError."""

    async def get_equipment_by_type(
        self, equipment_types: list[EquipmentType]
    ) -> dict[EquipmentType, list[FakeWaterHeater]]:
        raise asyncio.TimeoutError("network blip")


def _monitor_with_throwing(state_file: str) -> tuple[RheemMonitor, FakePushover]:
    api = ThrowingEcoNetApi()

    async def factory() -> ThrowingEcoNetApi:
        return api

    client = RheemClient("u@example.com", "pw", api_factory=factory)
    pushover = FakePushover()
    logger = logging.getLogger("test_rheem")
    monitor = RheemMonitor(
        client=client,
        pushover=pushover,
        logger=logger,
        state_file=state_file,
    )
    return monitor, pushover


def test_transient_network_error_does_not_propagate(tmp_path: Path) -> None:
    """A non-PyeconetError (e.g. asyncio.TimeoutError) is caught, not raised."""
    state = str(tmp_path / "state.json")
    monitor, pushover = _monitor_with_throwing(state)
    # Should return [] without raising.
    result = asyncio.run(monitor.check_once())
    assert result == []
    # No Pushover spam for transient errors (only auth/api get P0).
    assert pushover.sent == []


def test_run_continuous_survives_transient_error(tmp_path: Path) -> None:
    """run_continuous must not die on a transient error mid-cycle."""
    state = str(tmp_path / "state.json")
    monitor, _ = _monitor_with_throwing(state)
    calls = 0

    async def stop_after(n: int) -> None:
        nonlocal calls
        while calls < n:
            await monitor.check_once()
            calls += 1

    # If check_once raised, this would propagate and fail the test.
    asyncio.run(stop_after(3))
    assert calls == 3


def test_save_state_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    """_save_state writes via tmp+os.replace; no .tmp file remains."""
    state = str(tmp_path / "state.json")
    monitor, _ = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)], state
    )
    asyncio.run(monitor.check_once())
    # State file is valid JSON.
    with open(state) as f:
        data = json.load(f)
    assert data == {"alerted": {"S1": "p1"}, "setpoints": {"S1": 120}}
    # No leftover tmp file.
    assert not Path(state + ".tmp").exists()


def test_load_state_recovers_from_corrupt_file(tmp_path: Path) -> None:
    """A truncated/corrupt state file is ignored (fresh start), not fatal."""
    state = str(tmp_path / "state.json")
    Path(state).write_text('{"alerted": {"S1": "p1')  # truncated
    monitor, _ = _monitor_with(
        [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)], state
    )
    # Loaded fresh (empty), then re-alerts because it's low.
    assert monitor.alerted == {}


def test_mid_threshold_gate_blocks_premature_clear(tmp_path: Path) -> None:
    """Recovery must reach mid_threshold, not merely exceed low_threshold.

    Regression for the dead-`mid_threshold` bug: with mid_threshold=100, a
    tank at 66 (above low but below mid) must hold the alert, not clear it.
    """
    state = str(tmp_path / "state.json")
    heaters = [FakeWaterHeater(serial_number="S1", name="Garage", availability=33)]
    monitor, pushover = _monitor_with(heaters, state, mid_threshold=100)
    asyncio.run(monitor.check_once())  # P1 fired
    assert monitor.alerted["S1"] == "p1"
    # Recover to 66 — above low_threshold (33) but below mid_threshold (100).
    heaters[0].availability = 66
    asyncio.run(monitor.check_once())
    # No clear fired; alert still active.
    assert len(pushover.sent) == 1
    assert "S1" in monitor.alerted
    # Now reach mid_threshold -> clear.
    heaters[0].availability = 100
    asyncio.run(monitor.check_once())
    assert len(pushover.sent) == 2
    assert pushover.sent[1][2] == -1
    assert "S1" not in monitor.alerted
