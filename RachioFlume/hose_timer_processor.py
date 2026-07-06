"""Per-cycle hose-timer processor.

Polls each hose-timer base station, detects valve run transitions
(start / end) via the `lastWateringAction` discriminator, persists
events and sessions, and emits a P-1 pushover zone-end report when a
run completes — same format as the controller path, with the device
label and the configured baseline GPM appended for context.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from RachioFlume.alert_rules import (
    ZoneThreshold,
    compact_zone_label,
    send_zone_outcome_pushover,
)
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import FlumeClient
from RachioFlume.rachio_hose_client import HoseValve, RachioHoseClient
from lib.notifications import Notifier
from lib.logger import get_logger


def _state_key(valve_id: str) -> str:
    return f"hose::valve::{valve_id}::last_action"


# Cross-component key: AlertEngine reads this to suppress Flume rule alerts
# while a hose-timer valve is running or recently ran. Mirrors the controller's
# in-memory rachio state — kept in DB metadata so the two processors stay
# decoupled (HoseTimerProcessor writes; AlertEngine reads).
_HOSE_LAST_ACTIVE_KEY = "alert::__hose__::last_active"


class HoseTimerProcessor:
    """Detect runs on hose-timer valves and emit pushover zone-end reports.

    Threshold lookup uses valve name as the zone_key (matches
    cfg.rachio_flume.alerts.zone_thresholds[device_label][valve_name]).
    """

    def __init__(
        self,
        client: RachioHoseClient,
        pushover: Notifier,
        db: WaterTrackingDB,
        thresholds: Optional[dict[str, ZoneThreshold]] = None,
        flume_client: Optional[FlumeClient] = None,
        absolute_gpm: float = 0.5,
        percent_above: float = 10.0,
        min_runtime_minutes: int = 5,
    ) -> None:
        self.client = client
        self.pushover = pushover
        self.db = db
        self.thresholds = thresholds or {}
        self.flume = flume_client
        self.absolute_gpm = absolute_gpm
        self.percent_above = percent_above
        self.min_runtime_minutes = min_runtime_minutes
        self.logger = get_logger(__name__)

    def evaluate(self, *, dry_run: bool = False, now: Optional[datetime] = None) -> list[dict]:
        if now is None:
            now = datetime.now()
        results: list[dict] = []

        try:
            valves = self.client.list_valves()
        except Exception as e:
            self.logger.error(f"listValves failed for '{self.client.label}': {e}")
            return [{"error": str(e), "device": self.client.label}]

        # Persist current valve roster for inventory + reporter joins.
        if not dry_run and valves:
            self.db.save_hose_valves([v.model_dump() for v in valves])

        any_active = False
        for valve in valves:
            entry = self._evaluate_valve(valve, now, dry_run)
            results.append(entry)
            if entry["action"] in ("run_started", "still_running", "run_completed"):
                any_active = True

        # Stamp last-active timestamp so AlertEngine can suppress Flume rules
        # while a hose valve is running or just ran.
        if any_active and not dry_run:
            self.db.set_metadata(
                _HOSE_LAST_ACTIVE_KEY,
                json.dumps({"at": now.isoformat(), "device": self.client.label}),
            )

        return results

    def _evaluate_valve(self, valve: HoseValve, now: datetime, dry_run: bool) -> dict:
        action = valve.last_watering_action
        cached_blob = self.db.get_metadata(_state_key(valve.id))
        cached: Optional[dict] = None
        if cached_blob:
            try:
                cached = json.loads(cached_blob)
            except json.JSONDecodeError as e:
                self.logger.warning(f"Corrupt cached state for valve {valve.id} ({e}); ignoring")
                cached = None

        entry: dict = {
            "device": self.client.label,
            "valve": valve.name,
            "action": "nothing",
        }

        if action:
            start_dt = RachioHoseClient.parse_action_start(action)
            duration_sec = RachioHoseClient.parse_action_duration(action)
            if start_dt is None:
                self.logger.warning(
                    f"hose '{self.client.label}/{valve.name}' lastWateringAction missing parseable start"
                )
                return entry

            cached_start = cached.get("start") if cached else None
            if cached_start != start_dt.isoformat():
                # New run started since last poll
                if not dry_run:
                    self.db.save_hose_watering_event(
                        {
                            "valve_id": valve.id,
                            "base_station_id": valve.base_station_id,
                            "event_date": start_dt,
                            "event_type": "ZONE_STARTED",
                            "duration_seconds": duration_sec,
                            "reason": action.get("reason"),
                            "flow_detected": action.get("flowDetected"),
                        }
                    )
                    self.db.set_metadata(
                        _state_key(valve.id),
                        json.dumps(
                            {
                                "start": start_dt.isoformat(),
                                "duration_seconds": duration_sec,
                                "reason": action.get("reason"),
                                "flow_detected": action.get("flowDetected"),
                                "valve_name": valve.name,
                                "finalized": False,
                            }
                        ),
                    )
                entry["action"] = "run_started"
                entry["start"] = start_dt.isoformat()
                entry["duration_seconds"] = duration_sec
                self.logger.info(
                    f"hose run started: '{self.client.label}/{valve.name}' "
                    f"start={start_dt.isoformat()} dur={duration_sec}s"
                )
            else:
                entry["action"] = "still_running"
        else:
            # No active action. If we have a cached unfinalized run whose
            # window has elapsed, finalize it.
            if cached and not cached.get("finalized"):
                start_dt = datetime.fromisoformat(cached["start"])
                duration_sec = int(cached.get("duration_seconds") or 0)
                end_dt = start_dt + timedelta(seconds=duration_sec)
                if now >= end_dt:
                    flow_detected = cached.get("flow_detected")
                    total_gal, avg_gpm = self._flume_window_flow(start_dt, end_dt)
                    if not dry_run:
                        self.db.save_hose_watering_event(
                            {
                                "valve_id": valve.id,
                                "base_station_id": valve.base_station_id,
                                "event_date": end_dt,
                                "event_type": "ZONE_COMPLETED",
                                "duration_seconds": duration_sec,
                                "reason": cached.get("reason"),
                                "flow_detected": flow_detected,
                            }
                        )
                        self.db.save_hose_zone_session(
                            {
                                "valve_id": valve.id,
                                "base_station_id": valve.base_station_id,
                                "valve_name": valve.name,
                                "base_station_label": valve.base_station_label,
                                "start_time": start_dt,
                                "end_time": end_dt,
                                "duration_seconds": duration_sec,
                                "flow_detected": flow_detected,
                                "total_water_used": total_gal,
                                "average_flow_rate": avg_gpm,
                            }
                        )
                        self.db.set_metadata(
                            _state_key(valve.id),
                            json.dumps({**cached, "finalized": True}),
                        )
                        self._send_zone_outcome(
                            valve, duration_sec, avg_gpm, total_gal, flow_detected
                        )
                    entry["action"] = "run_completed"
                    entry["duration_seconds"] = duration_sec
                    entry["flow_detected"] = flow_detected
                    entry["avg_gpm"] = avg_gpm
                    entry["total_gal"] = total_gal
                    self.logger.info(
                        f"hose run completed: '{self.client.label}/{valve.name}' "
                        f"dur={duration_sec}s avg_gpm={avg_gpm:.2f} total_gal={total_gal:.1f} "
                        f"flow_detected={flow_detected}"
                    )

        return entry

    def _flume_window_flow(self, start_dt: datetime, end_dt: datetime) -> tuple[float, float]:
        """Sum Flume per-minute readings over the run window.

        Returns (total_gallons, avg_gpm). Flume measures whole-house water,
        so non-irrigation use during the window inflates the number — same
        caveat as the controller path. Returns (0, 0) if Flume unavailable
        or no readings.
        """
        if self.flume is None:
            return 0.0, 0.0
        try:
            readings = self.flume.get_usage(start_dt, end_dt, bucket="MIN")
        except Exception as e:
            self.logger.warning(f"Flume window query failed: {e}")
            return 0.0, 0.0
        if not readings:
            return 0.0, 0.0
        total_gal = sum(r.value for r in readings)
        # Per-minute bucket; len(readings) is minute count
        avg_gpm = total_gal / len(readings) if readings else 0.0
        return total_gal, avg_gpm

    def _send_zone_outcome(
        self,
        valve: HoseValve,
        duration_sec: int,
        avg_gpm: float,
        total_gal: float,
        flow_detected: Optional[bool],
    ) -> None:
        """Hose valve zone-end notification. Delegates to the shared helper
        in alert_rules so the format stays in lockstep with the controller
        path. The trimmed header clusters visually with controller Pushover
        entries.
        """
        zt = self.thresholds.get(valve.name)
        baseline = zt.avg_gpm if zt else 0.0
        threshold = (
            zt.compute_threshold(self.absolute_gpm, self.percent_above) if zt else self.absolute_gpm
        )

        sensor_line = (
            "Flow sensor: detected"
            if flow_detected
            else ("Flow sensor: NOT detected" if flow_detected is False else "")
        )

        send_zone_outcome_pushover(
            pushover=self.pushover,
            logger=self.logger,
            log_label=f"'{valve.base_station_label}/{valve.name}'",
            header=f"'{compact_zone_label(valve.name)}' @ {valve.base_station_label}",
            runtime_min=duration_sec / 60.0,
            avg_gpm=avg_gpm,
            total_gal=total_gal,
            baseline=baseline,
            threshold=threshold,
            min_runtime_minutes=self.min_runtime_minutes,
            extra_lines=[sensor_line] if sensor_line else None,
        )
