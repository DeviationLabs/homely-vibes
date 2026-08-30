"""Rachio Smart Hose Timer client (cloud-rest.rach.io/valve/*).

The hose-timer API is a separate service from the controller API
(api.rach.io/1/public/device/*) but accepts the same Bearer api_key.
Unlike the controller API, there is NO history endpoint — historical runs
must be synthesized from state-transition polling of `getValve`.

When a valve is running, getValve returns:
    state.reportedState.lastWateringAction = {
        "start": "2026-06-27T07:46:46Z",
        "durationSeconds": "30",
        "reason": "QUICK_RUN",
        "flowDetected": false
    }
The field disappears ~5-10s after the run completes. Run detection caches
the last-seen action and synthesizes ZONE_STARTED on first observation,
ZONE_COMPLETED on disappearance (or when start+duration elapses).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel

from lib.logger import get_logger


class HoseValve(BaseModel):
    """One hose-timer valve."""

    id: str
    base_station_id: str
    base_station_label: str
    name: str
    default_runtime_seconds: int
    detect_flow: bool
    battery_status: Optional[str] = None
    connected: bool = True
    last_watering_action: Optional[Dict[str, Any]] = None


class RachioHoseClient:
    """Client for one Smart Hose Timer base station and its valves."""

    BASE_URL = "https://cloud-rest.rach.io"

    def __init__(self, api_key: str, base_station_id: str, label: str):
        self.api_key = api_key
        self.base_station_id = base_station_id
        self.label = label
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.logger = get_logger(__name__)
        self.logger.info(
            f"Hose timer client initialized: label='{label}' base_station={base_station_id}"
        )

    def get_base_station(self) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/valve/getBaseStation/{self.base_station_id}"
        r = requests.get(url, headers=self.headers, timeout=10)
        r.raise_for_status()
        body: Dict[str, Any] = r.json()
        bs: Dict[str, Any] = body.get("baseStation", {})
        return bs

    def list_valves(self) -> List[HoseValve]:
        """Fetch all valves under this base station."""
        url = f"{self.BASE_URL}/valve/listValves/{self.base_station_id}"
        r = requests.get(url, headers=self.headers, timeout=10)
        r.raise_for_status()
        body: Dict[str, Any] = r.json()
        valves: List[HoseValve] = []
        for v in body.get("valves", []):
            reported = (v.get("state") or {}).get("reportedState") or {}
            try:
                runtime_sec = int(reported.get("defaultRuntimeSeconds", "0"))
            except (TypeError, ValueError):
                runtime_sec = 0
            valves.append(
                HoseValve(
                    id=v["id"],
                    base_station_id=self.base_station_id,
                    base_station_label=self.label,
                    name=v["name"],
                    default_runtime_seconds=runtime_sec,
                    detect_flow=bool(v.get("detectFlow", False)),
                    battery_status=reported.get("batteryStatus"),
                    connected=bool(reported.get("connected", True)),
                    last_watering_action=reported.get("lastWateringAction"),
                )
            )
        self.logger.info(f"Found {len(valves)} valves on '{self.label}'")
        return valves

    def get_valve(self, valve_id: str) -> HoseValve:
        """Fetch one valve's current state (used for active-zone checks)."""
        url = f"{self.BASE_URL}/valve/getValve/{valve_id}"
        r = requests.get(url, headers=self.headers, timeout=10)
        r.raise_for_status()
        v = r.json().get("valve", {})
        reported = (v.get("state") or {}).get("reportedState") or {}
        try:
            runtime_sec = int(reported.get("defaultRuntimeSeconds", "0"))
        except (TypeError, ValueError):
            runtime_sec = 0
        return HoseValve(
            id=v["id"],
            base_station_id=self.base_station_id,
            base_station_label=self.label,
            name=v["name"],
            default_runtime_seconds=runtime_sec,
            detect_flow=bool(v.get("detectFlow", False)),
            battery_status=reported.get("batteryStatus"),
            connected=bool(reported.get("connected", True)),
            last_watering_action=reported.get("lastWateringAction"),
        )

    @staticmethod
    def parse_action_start(action: Dict[str, Any]) -> Optional[datetime]:
        """Parse the ISO8601 'start' field from a lastWateringAction."""
        s = action.get("start")
        if not s:
            return None
        # Rachio returns "2026-06-27T07:46:46Z" — handle trailing Z.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                # Strip tz to align with the rest of the codebase (naive local).
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except ValueError:
            return None

    @staticmethod
    def parse_action_duration(action: Dict[str, Any]) -> int:
        try:
            return int(action.get("durationSeconds", "0"))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def utcnow_naive() -> datetime:
        """Return current time as naive datetime (matches codebase convention)."""
        return datetime.now(timezone.utc).astimezone().replace(tzinfo=None)
