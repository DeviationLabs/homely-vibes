"""Usage alert engine for RachioFlume.

Runs at the end of every collector cycle. For each rule:
  1. Skip if Rachio is currently irrigating (treat as suppressed — do NOT update state).
  2. Query last `duration_minutes` of per-min Flume readings.
  3. Apply `_rule_matches` predicate to decide if condition is active.
  4. Apply `_decide_action` state machine to choose FIRE / FIRE_CLEAR / NOTHING.
  5. Send Pushover and persist state.

All "fire" alerts are Pushover priority 2 (emergency — retries until acked).
"Clear" alerts are priority 0 (normal).
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


# Extra minutes of suppression added after Rachio reports inactive. This
# covers the gap between the cycle where we last saw Rachio active and
# whenever it actually stopped — without this slack, the very next cycle
# queries Flume readings that overlap with the just-ended irrigation and
# false-fires. 10 min comfortably exceeds typical poll cadence.
RACHIO_POST_ACTIVE_SLACK_MINUTES = 10

_RACHIO_STATE_KEY = "alert::__rachio__::last_active"


class AlertAction(str, Enum):
    NOTHING = "nothing"
    FIRE = "fire"  # priority 2
    FIRE_CLEAR = "fire_clear"  # priority 0


@dataclass
class AlertState:
    """Persisted per-rule state."""

    last_state: Optional[str] = None  # "active" | "clear" | None (never evaluated)
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


class AlertEngine:
    """Evaluate alert rules against Flume data and dispatch Pushover notifications."""

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

    def _rule_matches(self, readings: list[WaterReading], rule: AlertRule) -> bool:
        """Return True if the mean flow over the trailing window meets the rule threshold.

        Using mean (not strict all-minutes) so that one or two zero-reading minutes from
        Flume's sampling cadence don't disqualify an otherwise sustained flow event. A real
        leak or pipe break will still average well above its threshold; a momentary spike
        among mostly-zero minutes will not.
        """
        if len(readings) < rule.duration_minutes:
            return False
        recent = readings[-rule.duration_minutes :]
        mean_gpm = sum(r.value for r in recent) / len(recent)
        return mean_gpm >= rule.min_gpm

    # ------------------------------------------------------------------ #
    # USER CONTRIBUTION SLOT 2: fire/clear state machine                  #
    # ------------------------------------------------------------------ #
    # Given the current evaluation, prior state, and rule re-trigger
    # cadence, decide what to do.
    #
    # Default semantics:
    #   - muted (mute_until in future)            -> NOTHING
    #   - active now, was clear/None              -> FIRE (priority 2)
    #   - active now, was active, retrigger due   -> FIRE (priority 2)
    #   - active now, was active, retrigger early -> NOTHING
    #   - clear now, was active                   -> FIRE_CLEAR (priority 0)
    #   - clear now, was clear/None               -> NOTHING
    #
    # Adjust if you want a different cadence (e.g. exponential backoff) or
    # different bootstrap behavior on first run.
    def _decide_action(
        self,
        is_active: bool,
        state: AlertState,
        rule: AlertRule,
        now: datetime,
    ) -> AlertAction:
        """Decide what to do this cycle. Returns one of AlertAction values."""
        if state.mute_until and state.mute_until > now:
            return AlertAction.NOTHING

        if is_active:
            if state.last_state != "active":
                return AlertAction.FIRE
            retrigger_due = state.last_fired_at is None or (
                now - state.last_fired_at >= timedelta(minutes=rule.retrigger_minutes)
            )
            return AlertAction.FIRE if retrigger_due else AlertAction.NOTHING

        # is_active is False
        if state.last_state == "active":
            return AlertAction.FIRE_CLEAR
        return AlertAction.NOTHING

    # ------------------------------------------------------------------ #
    # Engine internals                                                    #
    # ------------------------------------------------------------------ #

    def _load_state(self, rule: AlertRule) -> AlertState:
        return AlertState.from_json(self.db.get_metadata(_state_key(rule.name)))

    def _save_state(self, rule: AlertRule, state: AlertState) -> None:
        self.db.set_metadata(_state_key(rule.name), state.to_json())

    def _load_rachio_state(self) -> tuple[Optional[datetime], Optional[str]]:
        blob = self.db.get_metadata(_RACHIO_STATE_KEY)
        if not blob:
            return None, None
        d = json.loads(blob)
        at_iso = d.get("last_active_at")
        return (
            datetime.fromisoformat(at_iso) if at_iso else None,
            d.get("last_zone"),
        )

    def _save_rachio_state(self, at: datetime, zone_name: str) -> None:
        self.db.set_metadata(
            _RACHIO_STATE_KEY,
            json.dumps({"last_active_at": at.isoformat(), "last_zone": zone_name}),
        )

    def _fetch_window(self, rule: AlertRule, now: datetime) -> list[WaterReading]:
        start = now - timedelta(minutes=rule.duration_minutes)
        return self.flume.get_usage(start, now, bucket="MIN")

    def _send_fire(self, rule: AlertRule, readings: list[WaterReading]) -> None:
        recent = readings[-rule.duration_minutes :] if readings else []
        avg = sum(r.value for r in recent) / len(recent) if recent else 0.0
        msg = (
            f"{rule.name} alert: water flow has been >= {rule.min_gpm} gpm "
            f"for {rule.duration_minutes} min (avg {avg:.2f} gpm)."
        )
        self.pushover.send_message(msg, title=f"RachioFlume: {rule.name}", priority=2)
        self.logger.warning(f"FIRED priority-2 alert: {rule.name}")

    def _send_clear(self, rule: AlertRule) -> None:
        msg = f"{rule.name}: condition cleared. Water flow is no longer above threshold."
        self.pushover.send_message(msg, title=f"RachioFlume: {rule.name} cleared", priority=0)
        self.logger.info(f"FIRED clear notification: {rule.name}")

    async def evaluate(
        self, *, dry_run: bool = False, now: Optional[datetime] = None
    ) -> list[dict]:
        """Run one evaluation pass over all rules.

        Args:
            dry_run: If True, do not fire Pushover or persist state changes.
            now: Override the current time. Real callers pass None (uses datetime.now()).
                 The simulator passes simulated wall clock to drive playback.

        Returns a list of per-rule result dicts for logging/CLI display.
        """
        if now is None:
            now = datetime.now()
        results: list[dict] = []

        # Single Rachio check per cycle, shared across rules.
        rachio_active = self.rachio.get_active_zone()
        if rachio_active and not dry_run:
            self._save_rachio_state(now, rachio_active.name)
        last_rachio_active_at, last_rachio_zone = self._load_rachio_state()
        # Apply the in-memory update for dry-run consistency.
        if rachio_active:
            last_rachio_active_at = now
            last_rachio_zone = rachio_active.name
        if rachio_active:
            self.logger.info(
                f"Rachio zone '{rachio_active.name}' is irrigating; suppressing all rule evaluation."
            )
            if not dry_run:
                try:
                    gpm = self.flume.get_current_usage_rate()
                    gpm_str = f"{gpm:.1f} GPM" if gpm is not None else "N/A"
                except Exception:
                    gpm_str = "N/A"
                self.pushover.send_message(
                    f"Zone: {rachio_active.name}\nFlow: {gpm_str}",
                    title="RachioFlume: Irrigating",
                    priority=0,
                )

        for rule in self.rules:
            entry: dict = {"rule": rule.name, "action": AlertAction.NOTHING.value}

            # Suppression: active now OR recent enough that the rule's lookback
            # window may still overlap with the just-ended irrigation.
            suppressed_by: Optional[str] = None
            if rachio_active:
                suppressed_by = f"rachio:{rachio_active.name}"
            elif last_rachio_active_at is not None:
                threshold = timedelta(
                    minutes=rule.duration_minutes + RACHIO_POST_ACTIVE_SLACK_MINUTES
                )
                if now - last_rachio_active_at < threshold:
                    suppressed_by = f"rachio:{last_rachio_zone} (recent)"

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
                self._send_fire(rule, readings)
                state.last_state = "active"
                state.last_fired_at = now
                self._save_state(rule, state)
            elif action == AlertAction.FIRE_CLEAR:
                self._send_clear(rule)
                state.last_state = "clear"
                # leave last_fired_at as-is for history
                self._save_state(rule, state)
            else:
                # Even on NOTHING, persist the observed state so a future
                # re-fire decision sees the right last_state.
                new_state = "active" if is_active else "clear"
                if state.last_state != new_state:
                    state.last_state = new_state
                    self._save_state(rule, state)

            results.append(entry)

        return results

    # ------------------------------------------------------------------ #
    # CLI-facing helpers                                                  #
    # ------------------------------------------------------------------ #

    def mute(self, rule_name: str, hours: float) -> AlertState:
        """Mute a rule for `hours`. Returns the new state."""
        rule = self._find_rule(rule_name)
        state = self._load_state(rule)
        state.mute_until = datetime.now() + timedelta(hours=hours)
        self._save_state(rule, state)
        self.logger.info(f"Muted {rule.name} until {state.mute_until.isoformat()}")
        return state

    def unmute(self, rule_name: str) -> AlertState:
        """Clear a rule's mute. Returns the new state."""
        rule = self._find_rule(rule_name)
        state = self._load_state(rule)
        state.mute_until = None
        self._save_state(rule, state)
        self.logger.info(f"Unmuted {rule.name}")
        return state

    def status(self) -> list[dict]:
        """Return per-rule state for CLI display."""
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
