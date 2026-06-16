"""Tests for AlertEngine: predicate, state machine, Rachio suppression, mute."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from RachioFlume.alert_engine import AlertAction, AlertEngine, AlertState
from RachioFlume.alert_rules import AlertRule
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
    flume = MagicMock()
    rachio = MagicMock()
    rachio.get_active_zone.return_value = None
    pushover = MagicMock()
    pushover.send_message.return_value = True
    return AlertEngine(
        flume_client=flume,
        rachio_client=rachio,
        pushover=pushover,
        db=db,
        rules=[rule],
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


def test_predicate_mean_tolerates_brief_zero_when_average_still_meets_threshold(
    engine: AlertEngine, rule: AlertRule
) -> None:
    # mean([3.0, 0.0, 3.0, 4.5]) = 2.625 >= 2.6 — one zero-minute doesn't kill the alert
    assert engine._rule_matches(_readings([3.0, 0.0, 3.0, 4.5]), rule) is True


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
    """A 'Low Flow' rule (min_gpm=0.1) treats any sustained non-zero as active."""
    low_rule = AlertRule(name="Low Flow", min_gpm=0.1, duration_minutes=3, retrigger_minutes=30)
    readings = _readings([0.5, 0.2, 0.3])
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

    assert len(results) == 1
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
    # P0 irrigation notification sent (no alert fire/clear)
    engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
    call_args, call_kwargs = engine.pushover.send_message.call_args  # type: ignore[attr-defined]
    assert call_kwargs["priority"] == 0
    assert "Front Yard" in call_args[0]
    # State unchanged (no spurious "clear" later)
    assert engine._load_state(rule).last_state is None


async def test_evaluate_clear_emits_priority_0(engine: AlertEngine, rule: AlertRule) -> None:
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
    assert kwargs["priority"] == 0
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
