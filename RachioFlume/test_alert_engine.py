"""Tests for AlertEngine: predicate, state machine, Rachio suppression, mute."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from RachioFlume.alert_engine import AlertAction, AlertEngine, AlertState
from RachioFlume.alert_rules import AlertRule, ZoneThreshold
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import WaterReading
from RachioFlume.rachio_client import Zone


def _readings(values: list[float], end: datetime | None = None) -> list[WaterReading]:
    """Build a list of per-minute WaterReadings ending at `end` (default: now)."""
    end = end or datetime.now()
    return [
        WaterReading(timestamp=end - timedelta(minutes=len(values) - 1 - i), value=v)
        for i, v in enumerate(values)
    ]


@pytest.fixture
def db(tmp_path: Path) -> WaterTrackingDB:
    return WaterTrackingDB(str(tmp_path / "test.db"))


@pytest.fixture
def rule() -> AlertRule:
    return AlertRule(name="Mid Flow", min_gpm=2.6, duration_minutes=4, retrigger_minutes=30)


@pytest.fixture
def engine(db: WaterTrackingDB, rule: AlertRule) -> AlertEngine:
    # Seed a fresh reading so the Flume-outage watchdog stays quiet; outage
    # behavior has its own test section below.
    db.save_water_readings([WaterReading(timestamp=datetime.now(), value=0.0)])
    flume = MagicMock()
    rachio = MagicMock()
    rachio.get_active_zone.return_value = None
    pushover = MagicMock()
    pushover.send_message.return_value = True
    # Provide zone thresholds high enough that test flow rates don't trigger anomalies
    zone_thresholds = {
        1: ZoneThreshold(zone_key="1", avg_gpm=10.0),
        2: ZoneThreshold(zone_key="2", avg_gpm=10.0),
        3: ZoneThreshold(zone_key="3", avg_gpm=10.0),
    }
    return AlertEngine(
        flume_client=flume,
        rachio_client=rachio,
        pushover=pushover,
        db=db,
        rules=[rule],
        zone_thresholds=zone_thresholds,
    )


# ---------------------------------------------------------------------- #
# Predicate (Slot 1)                                                     #
# ---------------------------------------------------------------------- #


def test_predicate_fires_when_all_minutes_above_threshold(
    engine: AlertEngine, rule: AlertRule
) -> None:
    assert engine._rule_matches(_readings([3.0, 3.0, 3.0, 3.0]), rule) is True


def test_predicate_does_not_fire_on_single_zero_minute(
    engine: AlertEngine, rule: AlertRule
) -> None:
    # mean([3.0, 0.0, 3.0, 3.0]) = 2.25 < 2.6 — zero drags mean below threshold
    assert engine._rule_matches(_readings([3.0, 0.0, 3.0, 3.0]), rule) is False


def test_predicate_accepts_sustained_flow_with_low_cv(engine: AlertEngine, rule: AlertRule) -> None:
    # mean([3.0, 2.8, 3.0, 2.5]) = 2.825 >= 2.6, low CV → sustained flow accepted
    assert engine._rule_matches(_readings([3.0, 2.8, 3.0, 2.5]), rule) is True


def test_predicate_rejects_spiky_flow_even_if_mean_passes(
    engine: AlertEngine, rule: AlertRule
) -> None:
    # mean([3.0, 0.0, 3.0, 4.5]) = 2.625 >= 2.6 but CV ≈ 0.62 >> max_cv ≈ 0.25
    assert engine._rule_matches(_readings([3.0, 0.0, 3.0, 4.5]), rule) is False


def test_predicate_single_spike_among_zeros_does_not_fire() -> None:
    # mean([8.0, 0.0, 0.0, 0.0]) = 2.0 < 8.0 — a momentary surge is not a pipe break
    pipe_rule = AlertRule(name="Pipe Break", min_gpm=8.0, duration_minutes=4, retrigger_minutes=30)
    engine = AlertEngine(
        flume_client=MagicMock(),
        rachio_client=MagicMock(),
        pushover=MagicMock(),
        db=MagicMock(),
        rules=[pipe_rule],
    )
    assert engine._rule_matches(_readings([8.0, 0.0, 0.0, 0.0]), pipe_rule) is False


def test_predicate_does_not_fire_with_insufficient_samples(
    engine: AlertEngine, rule: AlertRule
) -> None:
    # Only 3 readings for a 4-minute rule
    assert engine._rule_matches(_readings([3.0, 3.0, 3.0]), rule) is False


def test_predicate_low_flow_rule_fires_on_trickle() -> None:
    """A 'Low Flow' rule (min_gpm=0.1) treats sustained low flow as active."""
    low_rule = AlertRule(name="Low Flow", min_gpm=0.1, duration_minutes=3, retrigger_minutes=30)
    readings = _readings([0.15, 0.12, 0.13])
    engine = AlertEngine(
        flume_client=MagicMock(),
        rachio_client=MagicMock(),
        pushover=MagicMock(),
        db=MagicMock(),
        rules=[low_rule],
    )
    assert engine._rule_matches(readings, low_rule) is True


# ---------------------------------------------------------------------- #
# State machine (Slot 2)                                                 #
# ---------------------------------------------------------------------- #


def test_state_machine_first_fire_on_active(engine: AlertEngine, rule: AlertRule) -> None:
    now = datetime.now()
    action = engine._decide_action(True, AlertState(), rule, now)
    assert action == AlertAction.FIRE


def test_state_machine_no_action_when_clear_and_no_history(
    engine: AlertEngine, rule: AlertRule
) -> None:
    now = datetime.now()
    action = engine._decide_action(False, AlertState(), rule, now)
    assert action == AlertAction.NOTHING


def test_state_machine_re_fire_after_retrigger_window(engine: AlertEngine, rule: AlertRule) -> None:
    now = datetime.now()
    state = AlertState(last_state="active", last_fired_at=now - timedelta(minutes=31))
    assert engine._decide_action(True, state, rule, now) == AlertAction.FIRE


def test_state_machine_silent_within_retrigger_window(engine: AlertEngine, rule: AlertRule) -> None:
    now = datetime.now()
    state = AlertState(last_state="active", last_fired_at=now - timedelta(minutes=10))
    assert engine._decide_action(True, state, rule, now) == AlertAction.NOTHING


def test_state_machine_clear_on_active_to_clear(engine: AlertEngine, rule: AlertRule) -> None:
    now = datetime.now()
    state = AlertState(last_state="active", last_fired_at=now - timedelta(minutes=5))
    assert engine._decide_action(False, state, rule, now) == AlertAction.FIRE_CLEAR


def test_state_machine_mute_blocks_fire(engine: AlertEngine, rule: AlertRule) -> None:
    now = datetime.now()
    state = AlertState(mute_until=now + timedelta(hours=1))
    assert engine._decide_action(True, state, rule, now) == AlertAction.NOTHING


def test_state_machine_expired_mute_allows_fire(engine: AlertEngine, rule: AlertRule) -> None:
    now = datetime.now()
    state = AlertState(mute_until=now - timedelta(minutes=1))
    assert engine._decide_action(True, state, rule, now) == AlertAction.FIRE


# ---------------------------------------------------------------------- #
# evaluate() — integration with Pushover, Flume, Rachio, DB              #
# ---------------------------------------------------------------------- #


async def test_evaluate_fires_priority_2_on_first_active(
    engine: AlertEngine, rule: AlertRule
) -> None:
    engine.flume.get_usage.return_value = _readings([3.0, 3.0, 3.0, 3.0])  # type: ignore[attr-defined]
    results = await engine.evaluate()

    # One entry per rule + the Flume-outage watchdog entry
    assert len(results) == 2
    assert results[0]["action"] == AlertAction.FIRE.value
    # Pushover called with priority=2 (emergency)
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
    _, kwargs = engine.pushover.send_message.call_args  # type: ignore[attr-defined]
    assert kwargs["priority"] == 2
    # State persisted as active
    state = engine._load_state(rule)
    assert state.last_state == "active"
    assert state.last_fired_at is not None


async def test_evaluate_suppressed_by_active_rachio_zone(
    engine: AlertEngine, rule: AlertRule
) -> None:
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z1", zone_number=3, name="Front Yard", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([9.0, 9.0, 9.0, 9.0])  # type: ignore[attr-defined]

    results = await engine.evaluate()

    assert results[0]["action"] == AlertAction.NOTHING.value
    assert "suppressed_by" in results[0]
    # No alert sent while irrigating (zone-end report fires later)
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]
    # State unchanged (no spurious "clear" later)
    assert engine._load_state(rule).last_state is None


async def test_evaluate_clear_emits_priority_neg1(engine: AlertEngine, rule: AlertRule) -> None:
    # Seed state as if rule was active last cycle
    engine._save_state(
        rule,
        AlertState(last_state="active", last_fired_at=datetime.now() - timedelta(minutes=5)),
    )
    engine.flume.get_usage.return_value = _readings([0.0, 0.0, 0.0, 0.0])  # type: ignore[attr-defined]

    results = await engine.evaluate()

    assert results[0]["action"] == AlertAction.FIRE_CLEAR.value
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
    _, kwargs = engine.pushover.send_message.call_args  # type: ignore[attr-defined]
    assert kwargs["priority"] == -1
    assert engine._load_state(rule).last_state == "clear"


async def test_evaluate_retrigger_after_window(engine: AlertEngine, rule: AlertRule) -> None:
    engine._save_state(
        rule,
        AlertState(last_state="active", last_fired_at=datetime.now() - timedelta(minutes=45)),
    )
    engine.flume.get_usage.return_value = _readings([3.0, 3.0, 3.0, 3.0])  # type: ignore[attr-defined]

    results = await engine.evaluate()

    assert results[0]["action"] == AlertAction.FIRE.value
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]


async def test_evaluate_silent_within_retrigger(engine: AlertEngine, rule: AlertRule) -> None:
    engine._save_state(
        rule,
        AlertState(last_state="active", last_fired_at=datetime.now() - timedelta(minutes=10)),
    )
    engine.flume.get_usage.return_value = _readings([3.0, 3.0, 3.0, 3.0])  # type: ignore[attr-defined]

    results = await engine.evaluate()

    assert results[0]["action"] == AlertAction.NOTHING.value
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]


async def test_evaluate_dry_run_does_not_send_or_persist(
    engine: AlertEngine, rule: AlertRule
) -> None:
    engine.flume.get_usage.return_value = _readings([3.0, 3.0, 3.0, 3.0])  # type: ignore[attr-defined]

    results = await engine.evaluate(dry_run=True)

    assert results[0]["action"] == AlertAction.FIRE.value
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]
    # No state written
    assert engine._load_state(rule).last_state is None


# ---------------------------------------------------------------------- #
# Mute / unmute                                                          #
# ---------------------------------------------------------------------- #


def test_mute_sets_mute_until(engine: AlertEngine, rule: AlertRule) -> None:
    state = engine.mute("Mid Flow", hours=2.0)
    assert state.mute_until is not None
    assert state.mute_until > datetime.now()


def test_unmute_clears_mute(engine: AlertEngine, rule: AlertRule) -> None:
    engine.mute("Mid Flow", hours=2.0)
    state = engine.unmute("Mid Flow")
    assert state.mute_until is None


def test_mute_unknown_rule_raises(engine: AlertEngine) -> None:
    with pytest.raises(ValueError):
        engine.mute("Nonexistent", hours=1.0)


async def test_muted_rule_does_not_fire_in_evaluate(engine: AlertEngine, rule: AlertRule) -> None:
    engine.mute("Mid Flow", hours=2.0)
    engine.flume.get_usage.return_value = _readings([3.0, 3.0, 3.0, 3.0])  # type: ignore[attr-defined]

    results = await engine.evaluate()

    assert results[0]["action"] == AlertAction.NOTHING.value
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------- #
# Zone-end reporting — zone transitions                                  #
# ---------------------------------------------------------------------- #


async def test_zone_transition_reports_previous_zone(engine: AlertEngine, rule: AlertRule) -> None:
    """When zone A transitions to zone B, zone A should be reported."""
    # Cycle 1: Zone A is active
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z1", zone_number=1, name="Front Lawn", enabled=True
    )
    # 7 minutes of active readings > min_runtime_minutes=5 → outcome fires
    engine.flume.get_usage.return_value = _readings([5.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]

    # Cycle 2: Zone A ended, Zone B started → report Zone A
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z2", zone_number=2, name="Back Lawn", enabled=True
    )
    # 7 minutes of active readings > min_runtime_minutes=5 → outcome fires
    engine.flume.get_usage.return_value = _readings([5.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()

    # Zone A should be reported
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
    call_args = engine.pushover.send_message.call_args  # type: ignore[attr-defined]
    assert "Front Lawn" in call_args[0][0]
    assert call_args[1]["priority"] == -1


async def test_zone_transition_multiple_zones(engine: AlertEngine, rule: AlertRule) -> None:
    """Multi-zone cycle: each zone gets reported when the next one starts."""
    zones = [
        Zone(id="z1", zone_number=1, name="Zone A", enabled=True),
        Zone(id="z2", zone_number=2, name="Zone B", enabled=True),
        Zone(id="z3", zone_number=3, name="Zone C", enabled=True),
    ]

    # Cycle 1: Zone A active
    engine.rachio.get_active_zone.return_value = zones[0]  # type: ignore[attr-defined]
    engine.flume.get_usage.return_value = _readings([4.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 0  # type: ignore[attr-defined]

    # Cycle 2: Zone A → Zone B transition → report Zone A
    engine.rachio.get_active_zone.return_value = zones[1]  # type: ignore[attr-defined]
    engine.flume.get_usage.return_value = _readings([4.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 1  # type: ignore[attr-defined]
    assert "Zone A" in engine.pushover.send_message.call_args_list[0][0][0]  # type: ignore[attr-defined]

    # Cycle 3: Zone B → Zone C transition → report Zone B
    engine.rachio.get_active_zone.return_value = zones[2]  # type: ignore[attr-defined]
    engine.flume.get_usage.return_value = _readings([4.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 2  # type: ignore[attr-defined]
    assert "Zone B" in engine.pushover.send_message.call_args_list[1][0][0]  # type: ignore[attr-defined]

    # Cycle 4: Zone C → idle → report Zone C
    engine.rachio.get_active_zone.return_value = None  # type: ignore[attr-defined]
    engine.flume.get_usage.return_value = _readings([4.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 3  # type: ignore[attr-defined]
    assert "Zone C" in engine.pushover.send_message.call_args_list[2][0][0]  # type: ignore[attr-defined]


async def test_zone_report_each_cycle(engine: AlertEngine, rule: AlertRule) -> None:
    """Each zone cycle should be reported with a cycle count."""
    # Cycle 1: Zone A active
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z1", zone_number=1, name="Zone A", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([3.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()

    # Cycle 2: Zone A → Zone B → report Zone A (Cycle 1)
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z2", zone_number=2, name="Zone B", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([3.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 1  # type: ignore[attr-defined]
    # cycle 1 has no label
    assert "Cycle" not in engine.pushover.send_message.call_args_list[0][0][0]  # type: ignore[attr-defined]

    # Cycle 3: Zone B → Zone A → report Zone B (Cycle 1)
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z1", zone_number=1, name="Zone A", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([3.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 2  # type: ignore[attr-defined]
    assert "Zone B" in engine.pushover.send_message.call_args_list[1][0][0]  # type: ignore[attr-defined]

    # Cycle 4: Zone A → Zone B → report Zone A (Cycle 2)
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z2", zone_number=2, name="Zone B", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([3.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 3  # type: ignore[attr-defined]
    assert "Zone A" in engine.pushover.send_message.call_args_list[2][0][0]  # type: ignore[attr-defined]
    assert "Cycle 2" in engine.pushover.send_message.call_args_list[2][0][0]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------- #
# Flume data-outage watchdog                                              #
# ---------------------------------------------------------------------- #


def _outage_entry(results: list[dict]) -> dict:
    matches = [r for r in results if r.get("rule") == "Flume Data Outage"]
    assert len(matches) == 1
    return matches[0]


async def test_flume_outage_fires_p2_when_db_has_no_readings(
    engine: AlertEngine, db: WaterTrackingDB
) -> None:
    # Wipe the seeded reading so the DB looks like Flume never reported.
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    results = await engine.evaluate()

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.FIRE.value
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
    args, kwargs = engine.pushover.send_message.call_args  # type: ignore[attr-defined]
    assert kwargs["priority"] == 2
    assert "Flume" in args[0]


async def test_flume_outage_fires_when_readings_stale(
    engine: AlertEngine, db: WaterTrackingDB
) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    stale_at = datetime.now() - timedelta(hours=2)
    db.save_water_readings([WaterReading(timestamp=stale_at, value=1.0)])
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    results = await engine.evaluate()

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.FIRE.value
    assert entry["last_reading_at"] == stale_at.isoformat()


async def test_flume_outage_silent_within_retrigger_window(
    engine: AlertEngine, db: WaterTrackingDB
) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    await engine.evaluate()  # first evaluate fires
    engine.pushover.send_message.reset_mock()  # type: ignore[attr-defined]
    results = await engine.evaluate()  # still stale, within retrigger window

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.NOTHING.value
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]


async def test_flume_outage_retriggers_after_cadence(
    engine: AlertEngine, db: WaterTrackingDB
) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    await engine.evaluate()
    engine.pushover.send_message.reset_mock()  # type: ignore[attr-defined]
    # Past the retrigger cadence (default 360 min) → fires again
    later = datetime.now() + timedelta(minutes=engine.flume_outage_retrigger_minutes + 1)
    results = await engine.evaluate(now=later)

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.FIRE.value
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]


async def test_flume_outage_clears_p0_on_recovery(engine: AlertEngine, db: WaterTrackingDB) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    await engine.evaluate()  # fires: DB empty
    engine.pushover.send_message.reset_mock()  # type: ignore[attr-defined]
    db.save_water_readings([WaterReading(timestamp=datetime.now(), value=0.5)])
    results = await engine.evaluate()  # recovered

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.FIRE_CLEAR.value
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
    _, kwargs = engine.pushover.send_message.call_args  # type: ignore[attr-defined]
    assert kwargs["priority"] == 0


async def test_flume_outage_quiet_with_fresh_readings(engine: AlertEngine) -> None:
    # Fixture seeds a fresh reading → watchdog reports clear, sends nothing.
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    results = await engine.evaluate()

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.NOTHING.value
    assert entry["is_active"] is False
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]


async def test_flume_outage_dry_run_does_not_send_or_persist(
    engine: AlertEngine, db: WaterTrackingDB
) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    results = await engine.evaluate(dry_run=True)

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.FIRE.value
    engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]
    assert db.get_metadata("alert::Flume Data Outage::state") is None


async def test_flume_outage_not_suppressed_by_active_zone(
    engine: AlertEngine, db: WaterTrackingDB
) -> None:
    """Irrigation suppression must not silence the outage watchdog."""
    with db.get_connection() as conn:
        conn.execute("DELETE FROM water_readings")
        conn.commit()
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z1", zone_number=1, name="Front Yard", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([0.0] * 4)  # type: ignore[attr-defined]

    results = await engine.evaluate()

    entry = _outage_entry(results)
    assert entry["action"] == AlertAction.FIRE.value
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]


async def test_rachio_idle_reports_last_zone(engine: AlertEngine, rule: AlertRule) -> None:
    """When Rachio goes idle, the last active zone should be reported."""
    # Cycle 1: Zone active
    engine.rachio.get_active_zone.return_value = Zone(  # type: ignore[attr-defined]
        id="z1", zone_number=1, name="Front Yard", enabled=True
    )
    engine.flume.get_usage.return_value = _readings([6.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 0  # type: ignore[attr-defined]

    # Cycle 2: Rachio idle → report the zone
    engine.rachio.get_active_zone.return_value = None  # type: ignore[attr-defined]
    engine.flume.get_usage.return_value = _readings([6.0] * 7)  # type: ignore[attr-defined]
    await engine.evaluate()
    assert engine.pushover.send_message.call_count == 1  # type: ignore[attr-defined]
    assert "Front Yard" in engine.pushover.send_message.call_args[0][0]  # type: ignore[attr-defined]
