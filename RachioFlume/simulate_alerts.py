"""Simulator: replay a synthetic dataset through the AlertEngine.

No Pushover, no real Flume / Rachio calls. Each step prints events to stdout.
Used both by the `rfmanager simulate` CLI and by test_alert_simulation.py.
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from RachioFlume.alert_engine import AlertEngine
from RachioFlume.alert_rules import AlertRule, load_rules_from_config
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import WaterReading
from RachioFlume.rachio_client import Zone
from RachioFlume.synthetic_data import SyntheticDataset, load_dataset_from_yaml


@dataclass
class CapturedPush:
    """One Pushover-like notification captured by the simulator (printed, not sent)."""

    when: datetime
    title: str
    message: str
    priority: int


class _FakeFlume:
    def __init__(self, dataset: SyntheticDataset) -> None:
        self.dataset = dataset

    def get_usage(self, start: datetime, end: datetime, bucket: str = "MIN") -> list[WaterReading]:
        return self.dataset.readings_for_window(start, end)


class _FakeRachio:
    def __init__(self, dataset: SyntheticDataset) -> None:
        self.dataset = dataset
        self.current_time: Optional[datetime] = None

    def get_active_zone(self) -> Optional[Zone]:
        if self.current_time is None:
            return None
        return self.dataset.rachio_active_at(self.current_time)


class _CapturingPushover:
    """Records send_message calls; never hits the network."""

    def __init__(self) -> None:
        self.sent: list[CapturedPush] = []
        self._clock: Optional[datetime] = None

    def set_clock(self, t: datetime) -> None:
        self._clock = t

    def send_message(self, message: str, title: Optional[str] = None, priority: int = 0) -> bool:
        when = self._clock or datetime.now()
        self.sent.append(
            CapturedPush(when=when, title=title or "", message=message, priority=priority)
        )
        return True


@dataclass
class SimulationResult:
    dataset: SyntheticDataset
    rules: list[AlertRule]
    fires: list[CapturedPush] = field(default_factory=list)
    suppressed_count: int = 0
    cycles: int = 0


async def run_simulation(
    dataset: SyntheticDataset,
    rules: list[AlertRule],
    *,
    poll_interval_minutes: int = 5,
    print_events: bool = True,
) -> SimulationResult:
    """Step through the dataset, evaluating rules each cycle. Prints to stdout."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    db = WaterTrackingDB(db_path)
    fake_flume = _FakeFlume(dataset)
    fake_rachio = _FakeRachio(dataset)
    fake_pushover = _CapturingPushover()
    engine = AlertEngine(
        flume_client=fake_flume,  # type: ignore[arg-type]
        rachio_client=fake_rachio,  # type: ignore[arg-type]
        pushover=fake_pushover,  # type: ignore[arg-type]
        db=db,
        rules=rules,
    )

    result = SimulationResult(dataset=dataset, rules=rules)
    sim_now = dataset.start
    step = timedelta(minutes=poll_interval_minutes)

    # Suppress engine + storage INFO/WARNING logs during simulation so the
    # screen output is pure event timeline.
    quieted_loggers = [
        logging.getLogger("RachioFlume.alert_engine"),
        logging.getLogger("RachioFlume.data_storage"),
    ]
    prior_levels = [(lg, lg.level) for lg in quieted_loggers]
    for lg in quieted_loggers:
        lg.setLevel(logging.ERROR)

    if print_events:
        _print_header(dataset, rules, poll_interval_minutes)

    try:
        while sim_now <= dataset.end:
            fake_rachio.current_time = sim_now
            fake_pushover.set_clock(sim_now)
            pre_count = len(fake_pushover.sent)
            results = await engine.evaluate(now=sim_now)
            result.cycles += 1

            for r in results:
                if r.get("suppressed_by"):
                    result.suppressed_count += 1

            # Print any pushes triggered by this cycle, as they happen.
            if print_events:
                for push in fake_pushover.sent[pre_count:]:
                    kind = "FIRE " if push.priority == 2 else "CLEAR"
                    print(f"  {push.when:%Y-%m-%d %H:%M}  P{push.priority}  {kind}  {push.title}")

            sim_now += step
    finally:
        for lg, lvl in prior_levels:
            lg.setLevel(lvl)

    result.fires = list(fake_pushover.sent)

    if print_events:
        _print_summary(result)

    Path(db_path).unlink(missing_ok=True)
    return result


def _print_header(dataset: SyntheticDataset, rules: list[AlertRule], poll_minutes: int) -> None:
    print("=" * 72)
    print(
        f"Simulation: {dataset.days} days from {dataset.start:%Y-%m-%d}  "
        f"poll every {poll_minutes} min"
    )
    print("-" * 72)
    print("Rules:")
    for r in rules:
        print(
            f"  {r.name:<11}  min_gpm={r.min_gpm:>5}  "
            f"window={r.duration_minutes:>4}min  retrigger={r.retrigger_minutes}min"
        )
    print("-" * 72)
    print("Events injected:")
    for ev in dataset.events:
        zone = f" [rachio:{ev.irrigation_zone.name}]" if ev.irrigation_zone else ""
        print(
            f"  {ev.start:%Y-%m-%d %H:%M}  {ev.label:<22}  "
            f"{ev.duration_minutes:>5}min @ {ev.gpm:>4} gpm{zone}"
        )
    print("-" * 72)
    print("Alerts fired (priority 2 = FIRE; priority 0 = CLEAR):")
    print("  (silent cycles and Rachio-suppressed cycles omitted)")


def _print_summary(result: SimulationResult) -> None:
    print("-" * 72)

    # Titles are "RachioFlume: <rule>" (fire) or "RachioFlume: <rule> cleared" (clear).
    fires_by_rule: dict[str, int] = {}
    clears_by_rule: dict[str, int] = {}
    for push in result.fires:
        title = push.title.removeprefix("RachioFlume: ")
        if title.endswith(" cleared"):
            rule = title.removesuffix(" cleared")
            clears_by_rule[rule] = clears_by_rule.get(rule, 0) + 1
        else:
            fires_by_rule[title] = fires_by_rule.get(title, 0) + 1

    print(
        f"Summary: {result.cycles} cycles, "
        f"{len(result.fires)} pushes "
        f"({sum(fires_by_rule.values())} fires, {sum(clears_by_rule.values())} clears), "
        f"{result.suppressed_count} suppressed by Rachio"
    )
    if fires_by_rule:
        print("  Fires by rule:  " + ", ".join(f"{k}={v}" for k, v in fires_by_rule.items()))
    if clears_by_rule:
        print("  Clears by rule: " + ", ".join(f"{k}={v}" for k, v in clears_by_rule.items()))
    print("=" * 72)


def run_simulation_from_yaml(
    yaml_path: str | Path,
    *,
    poll_interval_minutes: int = 5,
) -> SimulationResult:
    """Convenience entry-point used by the CLI."""
    dataset = load_dataset_from_yaml(yaml_path)
    rules = load_rules_from_config()
    return asyncio.run(
        run_simulation(
            dataset, rules, poll_interval_minutes=poll_interval_minutes, print_events=True
        )
    )


__all__ = [
    "CapturedPush",
    "SimulationResult",
    "run_simulation",
    "run_simulation_from_yaml",
]
