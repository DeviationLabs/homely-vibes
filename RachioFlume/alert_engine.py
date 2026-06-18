"""Zone-end reporting for RachioFlume.

Runs at the end of every collector cycle. Detects when a Rachio zone finishes
irrigating — either because a new zone started (zone transition) or because
Rachio went fully idle — and sends exactly **one** P-1 notification per zone
per day reporting:
  • Zone name
  • Runtime (minutes)
  • Average flow rate (GPM, computed from per-minute Flume readings)
  • Total water used (gallons)

Rule-based anomaly alerts (pipe break, leak, etc.) remain P2 (emergency)
and fire at most once per day per rule.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from lib.logger import get_logger
from lib.MyPushover import Pushover
from RachioFlume.alert_rules import AlertRule
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import FlumeClient, WaterReading
from RachioFlume.rachio_client import RachioClient

# Minutes to wait after Rachio reports inactive before sending the zone-end
# report. Covers the gap for the collector cycle to persist session data.
# Only applies when Rachio goes fully idle (not zone transitions, which are
# detected immediately).
RACHIO_POST_ACTIVE_SLACK_MINUTES = 10

_RACHIO_STATE_KEY = "alert::__rachio__::last_active"
_REPORTED_ZONES_KEY = "reported::zones::{date}"
_REPORTED_RULES_KEY = "reported::rules::{date}"


def _zone_name_matches(session_name: str, lookup_name: str) -> bool:
    """Check if session zone name matches lookup name (handles partial names).

    Session data uses short names from event summaries (e.g., "Z2 FS"),
    while active zone API returns full names (e.g., "Z2 FS - Sergio Inner").
    This function handles both exact matches and prefix matches.
    """
    if session_name == lookup_name:
        return True
    # Check if one is a prefix of the other
    return lookup_name.startswith(session_name) or session_name.startswith(lookup_name)


class AlertAction(str, Enum):
    NOTHING = "nothing"
    ZONE_REPORT = "zone_report"  # priority 1
    FIRE = "fire"  # priority 2 (emergency)
    FIRE_CLEAR = "fire_clear"  # priority 0


@dataclass
class AlertState:
    """Persisted per-rule state."""

    last_state: Optional[str] = None  # "active" | "clear" | None
    last_fired_at: Optional[datetime] = None
    mute_until: Optional[datetime] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "last_state": self.last_state,
                "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
                "mute_until": self.mute_until.isoformat() if self.mute_until else None,
            }
        )

    @classmethod
    def from_json(cls, blob: Optional[str]) -> "AlertState":
        if not blob:
            return cls()
        d = json.loads(blob)
        return cls(
            last_state=d.get("last_state"),
            last_fired_at=datetime.fromisoformat(d["last_fired_at"])
            if d.get("last_fired_at")
            else None,
            mute_until=datetime.fromisoformat(d["mute_until"]) if d.get("mute_until") else None,
        )


def _state_key(rule_name: str) -> str:
    return f"alert::{rule_name}::state"


def _today_key(template: str, now: datetime) -> str:
    return template.format(date=now.strftime("%Y-%m-%d"))


def _load_set(db: WaterTrackingDB, key: str) -> set[str]:
    blob = db.get_metadata(key)
    if not blob:
        return set()
    return set(json.loads(blob))


def _save_set(db: WaterTrackingDB, key: str, s: set[str]) -> None:
    db.set_metadata(key, json.dumps(sorted(s)))


def _load_count_map(db: WaterTrackingDB, key: str) -> dict[str, int]:
    blob = db.get_metadata(key)
    if not blob:
        return {}
    return json.loads(blob)  # type: ignore[no-any-return]


def _save_count_map(db: WaterTrackingDB, key: str, d: dict[str, int]) -> None:
    db.set_metadata(key, json.dumps(d))


class AlertEngine:
    """Zone-end reporting + rule-based anomaly detection."""

    def __init__(
        self,
        flume_client: FlumeClient,
        rachio_client: RachioClient,
        pushover: Pushover,
        db: WaterTrackingDB,
        rules: list[AlertRule],
    ) -> None:
        self.flume = flume_client
        self.rachio = rachio_client
        self.pushover = pushover
        self.db = db
        self.rules = rules
        self.logger = get_logger(__name__)

    # ------------------------------------------------------------------ #
    # Zone-end reporting                                                  #
    # ------------------------------------------------------------------ #

    def _load_rachio_state(self) -> tuple[Optional[datetime], Optional[str], Optional[int]]:
        blob = self.db.get_metadata(_RACHIO_STATE_KEY)
        if not blob:
            return None, None, None
        d = json.loads(blob)
        at_iso = d.get("last_active_at")
        return (
            datetime.fromisoformat(at_iso) if at_iso else None,
            d.get("last_zone"),
            d.get("last_zone_number"),
        )

    def _save_rachio_state(
        self, at: datetime, zone_name: Optional[str], zone_number: Optional[int]
    ) -> None:
        self.db.set_metadata(
            _RACHIO_STATE_KEY,
            json.dumps(
                {
                    "last_active_at": at.isoformat(),
                    "last_zone": zone_name,
                    "last_zone_number": zone_number,
                }
            ),
        )

    def _find_zone_session(
        self, zone_name: str, zone_number: Optional[int], now: datetime
    ) -> Optional[dict]:
        """Find the most recent session for a zone, using zone_number if available."""
        sessions = self.db.get_zone_sessions(now - timedelta(days=1), now)

        # Try matching by zone_number first (more reliable)
        if zone_number is not None:
            zone_sessions = [s for s in sessions if s.get("zone_number") == zone_number]
        else:
            # Fallback to name matching (handles partial names)
            zone_sessions = [s for s in sessions if _zone_name_matches(s["zone_name"], zone_name)]

        if not zone_sessions:
            return None

        # Return most recent session
        return sorted(
            zone_sessions,
            key=lambda s: s.get("end_time") or s.get("start_time") or datetime.min,
            reverse=True,
        )[0]

    def _send_zone_report(
        self, zone_name: str, runtime_min: float, avg_gpm: float, total_gal: float, cycle: int
    ) -> None:
        cycle_label = f" (Cycle {cycle})" if cycle > 1 else ""
        msg = (
            f"Zone '{zone_name}' completed{cycle_label}.\n"
            f"Runtime: {runtime_min:.0f} min\n"
            f"Avg flow: {avg_gpm:.2f} GPM\n"
            f"Total: {total_gal:.1f} gal"
        )
        self.pushover.send_message(msg, title="RachioFlume: Zone Report", priority=-1)
        self.logger.info(
            f"Zone-end report sent for '{zone_name}'{cycle_label}: {runtime_min:.0f} min, {avg_gpm:.2f} GPM, {total_gal:.1f} gal"
        )

    def _check_zone_end_report(
        self,
        zone_name: str,
        zone_number: Optional[int],
        last_active_at: Optional[datetime],
        now: datetime,
        dry_run: bool,
    ) -> bool:
        """Send a P-1 report for a zone that just ended.

        Reports every cycle (no per-day dedup). Includes cycle count in message
        so repeated runs of the same zone are distinguishable.

        Returns True if a report was sent (or would be sent in dry-run).
        """
        counts = _load_count_map(self.db, _today_key(_REPORTED_ZONES_KEY, now))
        cycle = counts.get(zone_name, 0) + 1

        # Look up the session data for this zone
        session = self._find_zone_session(zone_name, zone_number, now)

        if session:
            runtime_min = (session.get("duration_seconds") or 0) / 60.0
            avg_gpm = session.get("average_flow_rate") or 0.0
            total_gal = session.get("total_water_used") or 0.0
        else:
            # Fallback: estimate from Flume readings over the irrigation window
            self.logger.warning(
                f"No session found for zone '{zone_name}' (cycle {cycle}), estimating from Flume readings"
            )
            window_start = last_active_at or (now - timedelta(hours=1))
            readings = self.flume.get_usage(window_start, now, bucket="MIN")
            active_readings = [r for r in readings if r.value > 0.05]  # threshold to filter noise
            if active_readings:
                runtime_min = len(active_readings)
                avg_gpm = sum(r.value for r in active_readings) / len(active_readings)
                total_gal = sum(
                    r.value for r in active_readings
                )  # per-minute readings are in gallons
            else:
                runtime_min = 0
                avg_gpm = 0
                total_gal = 0

        if not dry_run:
            if runtime_min > 0:
                self._send_zone_report(zone_name, runtime_min, avg_gpm, total_gal, cycle)
            counts[zone_name] = cycle
            _save_count_map(self.db, _today_key(_REPORTED_ZONES_KEY, now), counts)
        else:
            self.logger.info(
                f"[DRY RUN] Would report zone '{zone_name}' (cycle {cycle}): {runtime_min:.0f} min, {avg_gpm:.2f} GPM, {total_gal:.1f} gal"
            )

        return True

    # ------------------------------------------------------------------ #
    # Rule-based anomaly detection (downgraded to P1)                     #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Variance-aware rule matching                                      #
    # ------------------------------------------------------------------#

    @staticmethod
    def _max_cv(min_gpm: float) -> float:
        """Max acceptable coefficient of variation for a rule.

        Lower thresholds need tighter variance control — Flume's absolute
        sensor noise is a larger fraction of a 0.1 GPM signal than an 8 GPM
        pipe break.  Formula calibrated empirically; capped to [0.15, 0.5].
        """
        cv = 0.5 - 0.04 * min_gpm
        return max(0.15, min(0.5, cv))

    def _rule_matches(self, readings: list[WaterReading], rule: AlertRule) -> bool:
        if len(readings) < rule.duration_minutes:
            return False
        recent = readings[-rule.duration_minutes :]
        values = [r.value for r in recent]
        mean_gpm = sum(values) / len(values)

        if mean_gpm < rule.min_gpm:
            return False

        # Variance guard: sustained flow must have low relative variation.
        # Spiky noise (a few high readings among mostly-zero minutes) will
        # have a high CV and be rejected even if the mean passes.
        if len(values) >= 2 and mean_gpm > 0:
            variance = sum((x - mean_gpm) ** 2 for x in values) / len(values)
            cv = variance**0.5 / mean_gpm
            if cv > self._max_cv(rule.min_gpm):
                self.logger.debug(
                    f"Rule '{rule.name}' mean {mean_gpm:.2f} passes threshold "
                    f"but CV {cv:.3f} > {self._max_cv(rule.min_gpm):.3f} — rejecting"
                )
                return False

        return True

    def _decide_action(
        self,
        is_active: bool,
        state: AlertState,
        rule: AlertRule,
        now: datetime,
    ) -> AlertAction:
        if state.mute_until and state.mute_until > now:
            return AlertAction.NOTHING

        if is_active:
            if state.last_state != "active":
                return AlertAction.FIRE
            retrigger_due = state.last_fired_at is None or (
                now - state.last_fired_at >= timedelta(minutes=rule.retrigger_minutes)
            )
            return AlertAction.FIRE if retrigger_due else AlertAction.NOTHING

        if state.last_state == "active":
            return AlertAction.FIRE_CLEAR
        return AlertAction.NOTHING

    def _load_state(self, rule: AlertRule) -> AlertState:
        return AlertState.from_json(self.db.get_metadata(_state_key(rule.name)))

    def _save_state(self, rule: AlertRule, state: AlertState) -> None:
        self.db.set_metadata(_state_key(rule.name), state.to_json())

    def _send_fire(self, rule: AlertRule, readings: list[WaterReading]) -> None:
        recent = readings[-rule.duration_minutes :] if readings else []
        avg = sum(r.value for r in recent) / len(recent) if recent else 0.0
        msg = (
            f"{rule.name}: sustained flow >= {rule.min_gpm} GPM "
            f"for {rule.duration_minutes} min (avg {avg:.2f} GPM)."
        )
        self.pushover.send_message(msg, title=f"RachioFlume: {rule.name}", priority=2)
        self.logger.warning(f"FIRED P2 alert: {rule.name}")

    def _send_clear(self, rule: AlertRule) -> None:
        msg = f"{rule.name}: condition cleared."
        self.pushover.send_message(msg, title=f"RachioFlume: {rule.name} cleared", priority=0)
        self.logger.info(f"Clear notification: {rule.name}")

    # ------------------------------------------------------------------ #
    # Main evaluate loop                                                  #
    # ------------------------------------------------------------------ #

    async def evaluate(
        self, *, dry_run: bool = False, now: Optional[datetime] = None
    ) -> list[dict]:
        if now is None:
            now = datetime.now()
        results: list[dict] = []

        # --- Rachio zone tracking ---
        # Load previous state BEFORE saving so we can detect transitions.
        last_rachio_active_at, last_rachio_zone, last_rachio_zone_number = self._load_rachio_state()
        rachio_active = self.rachio.get_active_zone()
        current_zone_name = rachio_active.name if rachio_active else None

        # Detect zone end: zone changed (transition) or Rachio went idle.
        zone_to_report: Optional[str] = None
        zone_to_report_number: Optional[int] = None
        zone_last_active_at: Optional[datetime] = None
        if last_rachio_zone is not None and current_zone_name != last_rachio_zone:
            zone_to_report = last_rachio_zone
            zone_to_report_number = last_rachio_zone_number
            zone_last_active_at = last_rachio_active_at

        # Persist current state for next cycle.
        # Only save when something changed (zone transition or active→idle).
        # Don't refresh last_active_at on every idle cycle — that would
        # keep the rule-suppression window open indefinitely.
        if not dry_run:
            state_changed = (zone_to_report is not None) or (
                rachio_active and (last_rachio_zone != rachio_active.name)
            )
            if state_changed:
                if rachio_active:
                    self._save_rachio_state(now, rachio_active.name, rachio_active.zone_number)
                else:
                    # Active→idle transition: keep last_active_at for suppression,
                    # clear zone to prevent re-detection.
                    self._save_rachio_state(last_rachio_active_at or now, None, None)

        # Effective values for rule-suppression logic below
        if rachio_active:
            last_rachio_active_at = now
            last_rachio_zone = rachio_active.name

        # --- Zone-end report (one per zone per day) ---
        if zone_to_report is not None:
            zone_reported = self._check_zone_end_report(
                zone_to_report,
                zone_to_report_number,
                zone_last_active_at,
                now,
                dry_run,
            )
            if zone_reported:
                results.append({"zone_report": True, "zone": zone_to_report})

        # --- Suppress rule evaluation while irrigating or within slack ---
        suppressed_by: Optional[str] = None
        if rachio_active:
            suppressed_by = f"rachio:{rachio_active.name}"
        elif last_rachio_active_at is not None:
            max_duration = max((r.duration_minutes for r in self.rules), default=0)
            threshold = timedelta(minutes=max_duration + RACHIO_POST_ACTIVE_SLACK_MINUTES)
            if now - last_rachio_active_at < threshold:
                suppressed_by = f"rachio:{last_rachio_zone} (recent)"

        if suppressed_by:
            self.logger.debug(f"Rule evaluation suppressed by: {suppressed_by}")

        # --- Rule-based anomaly detection ---
        reported_rules = _load_set(self.db, _today_key(_REPORTED_RULES_KEY, now))

        for rule in self.rules:
            entry: dict = {"rule": rule.name, "action": AlertAction.NOTHING.value}

            if suppressed_by:
                entry["suppressed_by"] = suppressed_by
                results.append(entry)
                continue

            try:
                readings = self._fetch_window(rule, now)
            except Exception as e:
                self.logger.error(f"Failed to fetch Flume window for rule {rule.name}: {e}")
                entry["error"] = str(e)
                results.append(entry)
                continue

            is_active = self._rule_matches(readings, rule)
            state = self._load_state(rule)
            action = self._decide_action(is_active, state, rule, now)
            entry["is_active"] = is_active
            entry["action"] = action.value
            entry["last_state"] = state.last_state
            entry["last_fired_at"] = (
                state.last_fired_at.isoformat() if state.last_fired_at else None
            )
            entry["mute_until"] = state.mute_until.isoformat() if state.mute_until else None

            if dry_run:
                results.append(entry)
                continue

            if action == AlertAction.FIRE:
                # One fire per rule per day
                if rule.name not in reported_rules:
                    self._send_fire(rule, readings)
                    state.last_state = "active"
                    state.last_fired_at = now
                    reported_rules.add(rule.name)
                    _save_set(self.db, _today_key(_REPORTED_RULES_KEY, now), reported_rules)
                else:
                    self.logger.debug(f"Rule '{rule.name}' already fired today, skipping")
                self._save_state(rule, state)
            elif action == AlertAction.FIRE_CLEAR:
                self._send_clear(rule)
                state.last_state = "clear"
                self._save_state(rule, state)
            else:
                new_state = "active" if is_active else "clear"
                if state.last_state != new_state:
                    state.last_state = new_state
                    self._save_state(rule, state)

            results.append(entry)

        return results

    def _fetch_window(self, rule: AlertRule, now: datetime) -> list[WaterReading]:
        start = now - timedelta(minutes=rule.duration_minutes)
        return self.flume.get_usage(start, now, bucket="MIN")

    # ------------------------------------------------------------------ #
    # CLI-facing helpers                                                  #
    # ------------------------------------------------------------------ #

    def mute(self, rule_name: str, hours: float) -> AlertState:
        rule = self._find_rule(rule_name)
        state = self._load_state(rule)
        state.mute_until = datetime.now() + timedelta(hours=hours)
        self._save_state(rule, state)
        self.logger.info(f"Muted {rule.name} until {state.mute_until.isoformat()}")
        return state

    def unmute(self, rule_name: str) -> AlertState:
        rule = self._find_rule(rule_name)
        state = self._load_state(rule)
        state.mute_until = None
        self._save_state(rule, state)
        self.logger.info(f"Unmuted {rule.name}")
        return state

    def status(self) -> list[dict]:
        out = []
        for rule in self.rules:
            state = self._load_state(rule)
            out.append(
                {
                    "rule": rule.name,
                    "min_gpm": rule.min_gpm,
                    "duration_minutes": rule.duration_minutes,
                    "retrigger_minutes": rule.retrigger_minutes,
                    "last_state": state.last_state,
                    "last_fired_at": state.last_fired_at.isoformat()
                    if state.last_fired_at
                    else None,
                    "mute_until": state.mute_until.isoformat() if state.mute_until else None,
                }
            )
        return out

    def _find_rule(self, name: str) -> AlertRule:
        for r in self.rules:
            if r.name.lower() == name.lower():
                return r
        valid = ", ".join(r.name for r in self.rules)
        raise ValueError(f"Unknown rule '{name}'. Valid rules: {valid}")


__all__ = ["AlertEngine", "AlertAction", "AlertState"]
