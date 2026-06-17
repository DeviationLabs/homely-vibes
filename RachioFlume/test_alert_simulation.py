"""End-to-end tests: drive AlertEngine through synthetic scenarios and assert
the expected alerts fire (or do not) for each scenario.

These tests use the real AlertEngine but back the Flume/Rachio clients with a
SyntheticDataset and capture Pushover sends instead of dispatching them.
"""

from datetime import datetime

import pytest

from RachioFlume.alert_rules import AlertRule
from RachioFlume.simulate_alerts import CapturedPush, SimulationResult, run_simulation
from RachioFlume.synthetic_data import SyntheticDataset


def _rules() -> list[AlertRule]:
    """Production-equivalent rules, used by every simulation test."""
    return [
        AlertRule(name="Pipe Break", min_gpm=8.0, duration_minutes=10, retrigger_minutes=30),
        AlertRule(name="High Flow", min_gpm=5.4, duration_minutes=4, retrigger_minutes=30),
        AlertRule(name="Mid Flow", min_gpm=2.6, duration_minutes=14, retrigger_minutes=30),
        AlertRule(name="Low Flow", min_gpm=0.1, duration_minutes=30, retrigger_minutes=30),
        AlertRule(name="Leak", min_gpm=0.1, duration_minutes=120, retrigger_minutes=30),
    ]


def _fires(result: SimulationResult, rule_name: str, priority: int = 1) -> list[CapturedPush]:
    """Return fire notifications for *rule_name* at the given priority (default 1)."""
    return [p for p in result.fires if p.title.endswith(rule_name) and p.priority == priority]


def _clears(result: SimulationResult, rule_name: str) -> list[CapturedPush]:
    return [p for p in result.fires if p.title == f"RachioFlume: {rule_name} cleared"]


@pytest.fixture
def start() -> datetime:
    return datetime(2026, 5, 1)


async def test_pipe_break_fires_within_window(start: datetime) -> None:
    ds = SyntheticDataset(start=start, days=1)
    ds.add_pipe_break(day=0, hour=10, duration_minutes=20, gpm=9.0)

    result = await run_simulation(ds, _rules(), poll_interval_minutes=5, print_events=False)

    pipe_fires = _fires(result, "Pipe Break")
    assert len(pipe_fires) >= 1, "Pipe Break should fire at least once"
    # First fire must be within (10 min rule window + 5 min poll lag) = 15 min of break start
    first = pipe_fires[0]
    assert (first.when - start).total_seconds() / 60 <= 10 * 60 + 15, (
        "Pipe Break should fire within 15 min after the 10-min window completes"
    )

    pipe_clears = _clears(result, "Pipe Break")
    assert len(pipe_clears) >= 1, "Pipe Break should emit a clear after the break ends"


async def test_slow_leak_fires_leak_rule_not_mid_or_high(start: datetime) -> None:
    ds = SyntheticDataset(start=start, days=4)
    ds.add_slow_leak(start_day=0, duration_hours=72, gpm=0.18)

    result = await run_simulation(ds, _rules(), poll_interval_minutes=5, print_events=False)

    assert len(_fires(result, "Leak")) >= 1, "Leak rule should fire"
    assert len(_fires(result, "Mid Flow")) == 0, (
        "0.18 gpm should never trigger Mid Flow (2.6 gpm threshold)"
    )
    assert len(_fires(result, "High Flow")) == 0
    assert len(_fires(result, "Pipe Break")) == 0


async def test_slow_leak_fires_once_per_day(start: datetime) -> None:
    ds = SyntheticDataset(start=start, days=4)
    ds.add_slow_leak(start_day=0, duration_hours=72, gpm=0.18)

    result = await run_simulation(ds, _rules(), poll_interval_minutes=5, print_events=False)

    leak_fires = _fires(result, "Leak")
    # Once-per-day rule: one fire per calendar day the leak is active.
    # 72 hr leak (May 1 00:00 → May 4 00:00) touches 4 calendar days → 3-4 fires.
    assert 3 <= len(leak_fires) <= 4, (
        f"expected 3-4 daily leak fires over 72 hr, got {len(leak_fires)}"
    )


async def test_irrigation_suppresses_concurrent_high_flow(start: datetime) -> None:
    ds = SyntheticDataset(start=start, days=1)
    # Strong sustained flow that WOULD fire High Flow, but with Rachio reporting active
    ds.add_irrigation(
        day=0, hour=6, zone_name="Front Yard", duration_minutes=30, gpm=6.0, zone_number=3
    )

    result = await run_simulation(ds, _rules(), poll_interval_minutes=5, print_events=False)

    assert len(_fires(result, "High Flow", priority=2)) == 0, (
        "Active Rachio zone should suppress High Flow"
    )
    assert result.suppressed_count > 0, "At least one cycle must record Rachio suppression"


async def test_short_shower_does_not_fire_mid_flow(start: datetime) -> None:
    ds = SyntheticDataset(start=start, days=1)
    # Shower: 8 min @ 2.4 gpm. Mid Flow needs 14 min @ 2.6 gpm — both miss.
    ds.add_household(day=0, hour=7, kind="shower")

    result = await run_simulation(ds, _rules(), poll_interval_minutes=5, print_events=False)

    assert len(_fires(result, "Mid Flow")) == 0
    assert len(_fires(result, "High Flow")) == 0
    assert len(_fires(result, "Pipe Break")) == 0


async def test_pipe_break_clear_arrives_only_after_active_to_clear(start: datetime) -> None:
    """A clear is emitted exactly once per active->clear transition."""
    ds = SyntheticDataset(start=start, days=1)
    ds.add_pipe_break(day=0, hour=10, duration_minutes=20, gpm=9.0)

    result = await run_simulation(ds, _rules(), poll_interval_minutes=5, print_events=False)

    clears = _clears(result, "Pipe Break")
    assert len(clears) == 1, f"Expected exactly one clear, got {len(clears)}"
