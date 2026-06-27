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

from RachioFlume.alert_rules import ZoneThreshold
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import FlumeClient
from RachioFlume.rachio_hose_client import HoseValve, RachioHoseClient
from lib.MyPushover import Pushover
from lib.logger import get_logger


def _state_key(valve_id: str) -> str:
    return f"hose::valve::{valve_id}::last_action"


class HoseTimerProcessor:
    """Detect runs on hose-timer valves and emit pushover zone-end reports.

    Threshold lookup uses valve name as the zone_key (matches
    cfg.rachio_flume.alerts.zone_thresholds[device_label][valve_name]).
    """

    def __init__(
        self,
        client: RachioHoseClient,
        pushover: Pushover,
        db: WaterTrackingDB,
        thresholds: Optional[dict[str, ZoneThreshold]] = None,
        flume_client: Optional[FlumeClient] = None,
    ) -> None:
        self.client = client
        self.pushover = pushover
        self.db = db
        self.thresholds = thresholds or {}
        self.flume = flume_client
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

        for valve in valves:
            entry = self._evaluate_valve(valve, now, dry_run)
            results.append(entry)

        return results

    def _evaluate_valve(self, valve: HoseValve, now: datetime, dry_run: bool) -> dict:
        action = valve.last_watering_action
        cached_blob = self.db.get_metadata(_state_key(valve.id))
        cached = json.loads(cached_blob) if cached_blob else None

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
                            }
                        )
                        self.db.set_metadata(
                            _state_key(valve.id),
                            json.dumps({**cached, "finalized": True}),
                        )
                        self._send_zone_report(
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

    def _send_zone_report(
        self,
        valve: HoseValve,
        duration_sec: int,
        avg_gpm: float,
        total_gal: float,
        flow_detected: Optional[bool],
    ) -> None:
        runtime_min = duration_sec / 60.0
        baseline = self.thresholds[valve.name].avg_gpm if valve.name in self.thresholds else None
        flow_line = (
            f"Avg flow: {avg_gpm:.2f} GPM (thresh {baseline:.2f})"
            if baseline is not None
            else f"Avg flow: {avg_gpm:.2f} GPM"
        )
        sensor_line = (
            "Flow sensor: detected"
            if flow_detected
            else ("Flow sensor: NOT detected" if flow_detected is False else "")
        )
        lines = [
            f"Valve '{valve.name}' on {valve.base_station_label} completed.",
            f"Runtime: {runtime_min:.0f} min",
            flow_line,
            f"Total: {total_gal:.1f} gal",
        ]
        if sensor_line:
            lines.append(sensor_line)
        msg = "\n".join(lines)
        self.pushover.send_message(msg, title="RachioFlume: Hose Run", priority=-1)
        self.logger.info(
            f"Hose zone-end report sent for '{valve.base_station_label}/{valve.name}': "
            f"{runtime_min:.0f} min, {avg_gpm:.2f} GPM, {total_gal:.1f} gal, "
            f"flow_detected={flow_detected}"
        )
