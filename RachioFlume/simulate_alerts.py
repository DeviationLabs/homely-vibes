"""Simulator: replay a dataset through the AlertEngine.

Two data sources are supported:
  - SyntheticDataset (from synthetic_data.py): hand-crafted YAML scenarios for testing.
  - DBReplayDataset: production water_readings + watering_events from a real SQLite DB.

Both data sources implement the same duck-typed interface:
  .start, .end (datetime), .days (int), .events (list, empty = no injected events)
  .readings_for_window(start, end) -> list[WaterReading]
  .rachio_active_at(t) -> Zone | None

No Pushover, no real Flume / Rachio calls during simulation. Events print to stdout.
Used by the `rfmanager simulate` / `rfmanager alerts replay` CLI and by test_alert_simulation.py.
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from RachioFlume.alert_engine import AlertEngine
from RachioFlume.alert_rules import (
    AlertRule,
    get_controller_zone_thresholds,
    load_zone_thresholds_from_config,
)
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import WaterReading
from RachioFlume.rachio_client import Zone
from lib.config import get_config


@dataclass
class CapturedPush:
    """One Pushover-like notification captured by the simulator (printed, not sent)."""

    when: datetime
    title: str
    message: str
    priority: int


class _FakeFlume:
    def __init__(self, dataset: Any) -> None:  # SyntheticDataset or DBReplayDataset
        self.dataset = dataset

    def get_usage(self, start: datetime, end: datetime, bucket: str = "MIN") -> list[WaterReading]:
        return self.dataset.readings_for_window(start, end)  # type: ignore[no-any-return]


class _FakeRachio:
    def __init__(self, dataset: Any) -> None:  # SyntheticDataset or DBReplayDataset
        self.dataset = dataset
        self.current_time: Optional[datetime] = None

    def get_active_zone(self) -> Optional[Zone]:
        if self.current_time is None:
            return None
        return self.dataset.rachio_active_at(self.current_time)  # type: ignore[no-any-return]


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
    dataset: Any  # SyntheticDataset or DBReplayDataset
    rules: list[AlertRule]
    fires: list[CapturedPush] = field(default_factory=list)
    suppressed_count: int = 0
    cycles: int = 0


async def run_simulation(
    dataset: Any,  # SyntheticDataset or DBReplayDataset (duck-typed interface)
    rules: list[AlertRule],
    *,
    poll_interval_minutes: int = 5,
    print_events: bool = True,
) -> SimulationResult:
    """Step through the dataset, evaluating rules each cycle. Prints to stdout.

    AlertEngine is constructed against the real merged config
    (default.yaml + local.yaml) — same `zone_anomaly` knobs and
    `zone_thresholds` that the production collector uses. Simulating is
    therefore also an end-to-end test of the user's config shape.
    """
    cfg = get_config()
    za_cfg = cfg.rachio_flume.alerts.zone_anomaly
    all_thresholds = load_zone_thresholds_from_config()
    # Synthetic scenarios reference controllers by zone_number. Pick the first
    # controller's baselines if one is configured; otherwise empty (anomaly
    # path silent, which is fine — sustained-flow rules still exercise).
    controllers = [d for d in cfg.rachio.devices if d.type == "controller"]
    primary_label = controllers[0].label if controllers else ""
    controller_thresholds = get_controller_zone_thresholds(all_thresholds, primary_label)

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
        zone_thresholds=controller_thresholds,
        absolute_gpm=za_cfg.absolute_gpm,
        percent_above=za_cfg.percent_above,
        min_runtime_minutes=za_cfg.min_runtime_minutes,
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
                    if push.priority == 2:
                        kind = "FIRE  "
                    elif push.priority == 0:
                        kind = "CLEAR "
                    elif push.priority == -1:
                        kind = "REPORT"
                    else:
                        kind = f"P{push.priority:>3}"
                    print(
                        f"  {push.when:%Y-%m-%d %H:%M}  P{push.priority:>2}  {kind}  {push.title}"
                    )

            sim_now += step
    finally:
        for lg, lvl in prior_levels:
            lg.setLevel(lvl)

    result.fires = list(fake_pushover.sent)

    if print_events:
        _print_summary(result)

    Path(db_path).unlink(missing_ok=True)
    return result


def _print_header(dataset: Any, rules: list[AlertRule], poll_minutes: int) -> None:
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
    if dataset.events:
        print("Events injected:")
        for ev in dataset.events:
            zone = f" [rachio:{ev.irrigation_zone.name}]" if ev.irrigation_zone else ""
            print(
                f"  {ev.start:%Y-%m-%d %H:%M}  {ev.label:<22}  "
                f"{ev.duration_minutes:>5}min @ {ev.gpm:>4} gpm{zone}"
            )
    else:
        print(
            f"Data source: production DB  "
            f"[{dataset.start:%Y-%m-%d %H:%M} \u2192 {dataset.end:%Y-%m-%d %H:%M}]"
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


class DBReplayDataset:
    """Replay dataset backed by the production SQLite DB (water_readings + watering_events).

    Implements the same duck-typed interface as SyntheticDataset so it can be passed
    directly to run_simulation(). Rachio active state is approximated from the stored
    watering events: a zone is considered active at time `t` if there is a ZONE_STARTED
    event before `t` with no corresponding ZONE_COMPLETED/ZONE_STOPPED after it and before `t`.
    """

    def __init__(self, db: WaterTrackingDB, start: datetime, end: datetime) -> None:
        self.db = db
        self.start = start
        self.end = end
        self.events: list[Any] = []  # no injected events; header shows DB range instead

    @property
    def days(self) -> int:
        return max(1, int((self.end - self.start).total_seconds() / 86400))

    def readings_for_window(self, start: datetime, end: datetime) -> list[WaterReading]:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT timestamp, value FROM water_readings "
                "WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
                (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
            )
            return [
                WaterReading(
                    timestamp=datetime.fromisoformat(str(row["timestamp"])),
                    value=float(row["value"]),
                )
                for row in cursor.fetchall()
            ]

    def rachio_active_at(self, t: datetime) -> Optional[Zone]:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT zone_name, zone_number FROM watering_events\n"
                "WHERE event_type = 'ZONE_STARTED' AND event_date <= ?\n"
                "AND NOT EXISTS (\n"
                "    SELECT 1 FROM watering_events we2\n"
                "    WHERE we2.zone_number = watering_events.zone_number\n"
                "      AND we2.event_type IN ('ZONE_COMPLETED', 'ZONE_STOPPED')\n"
                "      AND we2.event_date > watering_events.event_date\n"
                "      AND we2.event_date <= ?\n"
                ")\n"
                "ORDER BY event_date DESC LIMIT 1",
                (t.strftime("%Y-%m-%d %H:%M:%S"), t.strftime("%Y-%m-%d %H:%M:%S")),
            )
            row = cursor.fetchone()
            if row:
                return Zone(
                    id=f"z-{row['zone_number']}",
                    zone_number=row["zone_number"],
                    name=row["zone_name"],
                    enabled=True,
                )
            return None


def run_replay(
    db_path: str,
    hours: int,
    rules: list[AlertRule],
    *,
    poll_interval_minutes: int = 5,
) -> SimulationResult:
    """Replay the last `hours` hours of production DB data through the alert engine.

    Runs entirely offline: no Flume/Rachio API calls, no Pushover.
    Useful for validating predicate changes against real household water patterns.
    """
    db = WaterTrackingDB(db_path)
    end = datetime.now()
    start = end - timedelta(hours=hours)
    dataset = DBReplayDataset(db=db, start=start, end=end)
    return asyncio.run(
        run_simulation(
            dataset, rules, poll_interval_minutes=poll_interval_minutes, print_events=True
        )
    )


__all__ = [
    "CapturedPush",
    "DBReplayDataset",
    "SimulationResult",
    "run_replay",
    "run_simulation",
]
