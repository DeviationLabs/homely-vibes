"""Synthetic water-usage dataset for testing the RachioFlume alert engine.

The dataset is a list of overlapping events. Each event has a start time,
duration, GPM flow, and (optionally) an associated Rachio zone — if set,
the dataset reports that zone as actively irrigating during the event.

GPM at any minute is the sum of all events active at that minute, so you
can stack scenarios (e.g. a household shower running during a slow leak).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml  # type: ignore[import-untyped]

from RachioFlume.flume_client import WaterReading
from RachioFlume.rachio_client import Zone


HOUSEHOLD_RECIPES: dict[str, tuple[int, float]] = {
    # kind -> (duration_minutes, gpm)
    "shower": (8, 2.4),
    "dishwasher": (60, 0.8),
    "laundry": (45, 1.5),
    "toilet": (1, 4.0),
    "sink": (3, 1.2),
    "hose": (10, 3.5),
}


@dataclass
class Event:
    """One water-using event in the synthetic timeline."""

    start: datetime
    duration_minutes: int
    gpm: float
    label: str
    irrigation_zone: Optional[Zone] = None

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)

    def active_at(self, t: datetime) -> bool:
        return self.start <= t < self.end


@dataclass
class SyntheticDataset:
    """A timeline of water-usage events."""

    start: datetime
    days: int
    events: list[Event] = field(default_factory=list)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(days=self.days)

    # -------- event builders --------

    def add_household(self, day: int, hour: int, kind: str, minute: int = 0) -> "SyntheticDataset":
        if kind not in HOUSEHOLD_RECIPES:
            raise ValueError(f"Unknown household kind '{kind}'. Valid: {list(HOUSEHOLD_RECIPES)}")
        duration, gpm = HOUSEHOLD_RECIPES[kind]
        return self._add(
            day=day,
            hour=hour,
            minute=minute,
            duration_minutes=duration,
            gpm=gpm,
            label=f"household:{kind}",
        )

    def add_irrigation(
        self,
        day: int,
        hour: int,
        zone_name: str,
        duration_minutes: int,
        gpm: float,
        minute: int = 0,
        zone_number: int = 1,
    ) -> "SyntheticDataset":
        zone = Zone(id=f"z-{zone_number}", zone_number=zone_number, name=zone_name, enabled=True)
        return self._add(
            day=day,
            hour=hour,
            minute=minute,
            duration_minutes=duration_minutes,
            gpm=gpm,
            label=f"irrigation:{zone_name}",
            irrigation_zone=zone,
        )

    def add_slow_leak(
        self, start_day: int, duration_hours: int, gpm: float, hour: int = 0, minute: int = 0
    ) -> "SyntheticDataset":
        return self._add(
            day=start_day,
            hour=hour,
            minute=minute,
            duration_minutes=duration_hours * 60,
            gpm=gpm,
            label="slow_leak",
        )

    def add_pipe_break(
        self, day: int, hour: int, duration_minutes: int, gpm: float, minute: int = 0
    ) -> "SyntheticDataset":
        return self._add(
            day=day,
            hour=hour,
            minute=minute,
            duration_minutes=duration_minutes,
            gpm=gpm,
            label="pipe_break",
        )

    def _add(
        self,
        *,
        day: int,
        hour: int,
        minute: int,
        duration_minutes: int,
        gpm: float,
        label: str,
        irrigation_zone: Optional[Zone] = None,
    ) -> "SyntheticDataset":
        start = self.start + timedelta(days=day, hours=hour, minutes=minute)
        self.events.append(
            Event(
                start=start,
                duration_minutes=duration_minutes,
                gpm=gpm,
                label=label,
                irrigation_zone=irrigation_zone,
            )
        )
        return self

    # -------- queries --------

    def gpm_at(self, t: datetime) -> float:
        return sum(e.gpm for e in self.events if e.active_at(t))

    def rachio_active_at(self, t: datetime) -> Optional[Zone]:
        for e in self.events:
            if e.irrigation_zone is not None and e.active_at(t):
                return e.irrigation_zone
        return None

    def readings_for_window(self, start: datetime, end: datetime) -> list[WaterReading]:
        """Per-minute WaterReadings from `start` (inclusive) to `end` (exclusive)."""
        t = start.replace(second=0, microsecond=0)
        readings: list[WaterReading] = []
        while t < end:
            readings.append(WaterReading(timestamp=t, value=self.gpm_at(t)))
            t += timedelta(minutes=1)
        return readings


# -------- YAML loader --------


def load_dataset_from_yaml(path: str | Path) -> SyntheticDataset:
    """Load a SyntheticDataset from a YAML file.

    Expected schema:
        start_date: "2026-05-01"   # ISO date or datetime
        days: 30
        events:
          - {day: 1, hour: 7, minute: 30, kind: shower}
          - {day: 2, hour: 6, kind: irrigation, zone: "Front", duration_minutes: 30, gpm: 4.0}
          - {day: 3, hour: 0, kind: slow_leak, duration_hours: 72, gpm: 0.15}
          - {day: 7, hour: 14, kind: pipe_break, duration_minutes: 20, gpm: 9.0}
    """
    blob = yaml.safe_load(Path(path).read_text())
    start_raw = blob["start_date"]
    if isinstance(start_raw, str):
        start = datetime.fromisoformat(start_raw)
    else:
        # PyYAML parses bare YYYY-MM-DD into a date object
        start = datetime.combine(start_raw, datetime.min.time())
    days = int(blob["days"])
    ds = SyntheticDataset(start=start, days=days)

    for ev in blob.get("events", []):
        kind = ev["kind"]
        day = int(ev["day"])
        hour = int(ev["hour"])
        minute = int(ev.get("minute", 0))

        if kind in HOUSEHOLD_RECIPES:
            ds.add_household(day=day, hour=hour, kind=kind, minute=minute)
        elif kind == "irrigation":
            ds.add_irrigation(
                day=day,
                hour=hour,
                minute=minute,
                zone_name=ev["zone"],
                duration_minutes=int(ev["duration_minutes"]),
                gpm=float(ev["gpm"]),
                zone_number=int(ev.get("zone_number", 1)),
            )
        elif kind == "slow_leak":
            ds.add_slow_leak(
                start_day=day,
                hour=hour,
                minute=minute,
                duration_hours=int(ev["duration_hours"]),
                gpm=float(ev["gpm"]),
            )
        elif kind == "pipe_break":
            ds.add_pipe_break(
                day=day,
                hour=hour,
                minute=minute,
                duration_minutes=int(ev["duration_minutes"]),
                gpm=float(ev["gpm"]),
            )
        else:
            raise ValueError(f"Unknown event kind '{kind}' in {path}")

    return ds


__all__ = [
    "Event",
    "HOUSEHOLD_RECIPES",
    "SyntheticDataset",
    "load_dataset_from_yaml",
]
