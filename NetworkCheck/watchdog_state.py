#!/usr/bin/env python3
"""Persisted state for the uplink watchdog.

Split out because it is the part that must survive between cron ticks, and its
failure modes are its own: a truncated write resets the outage clock, and a
field that does not round-trip silently disables whatever depends on it.
"""

import contextlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional

SECONDS_PER_DAY = 86400


@dataclass
class WatchdogState:
    """Everything that must survive between cron ticks."""

    # One clock for both faults. It starts on the first unhealthy cycle of
    # either kind and only resets when the mesh is *fully* healthy, so a Deco
    # that alternates symptoms still accumulates toward a reboot.
    down_since: Optional[float] = None
    # What was wrong on the last unhealthy cycle, so the recovery notice can
    # name it. Purely for the alert text; nothing branches on it.
    fault_reason: Optional[str] = None
    # Did anything in this fault window deserve to be reported? Sticky for the
    # life of the window and cleared on recovery. The Deco's admin API times
    # out on roughly 2% of ticks, and a census that fails closed is
    # indistinguishable from a dead radio plane -- so without this, one 15s
    # read timeout sends "Recovered after 10 min (Wi-Fi down (0/25 clients))",
    # an alert that is not merely noisy but false. A window made only of
    # unreadable censuses still runs the clock; it just ends quietly.
    recovery_is_news: bool = False
    last_action_ts: Optional[float] = None
    last_auth_check_ts: Optional[float] = None
    # The gateway check runs on its own clock. Sharing last_auth_check_ts
    # would mean it never ran at all: every successful client census stamps
    # that one, so the Deco branch it gates is already permanently skipped.
    last_modem_check_ts: Optional[float] = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)

    def recent_actions(self, now: float) -> list[dict[str, Any]]:
        """Actions inside the trailing 24h window."""
        return [a for a in self.actions if now - a.get("ts", 0) < SECONDS_PER_DAY]

    def record_action(self, now: float) -> None:
        """Log an action and drop anything outside the 24h window.

        Pruned here, the one place the list grows, and against the caller's
        clock rather than ``time.time()`` so it stays deterministic in tests.
        """
        self.last_action_ts = now
        self.actions.append({"ts": now})
        self.actions = self.recent_actions(now)


def load_state(path: str, logger: logging.Logger) -> WatchdogState:
    """Read state from disk, falling back to a fresh one on anything unusable."""
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.debug("No usable watchdog state at %s; starting fresh", path)
        return WatchdogState()

    # `[1, 2]` is valid JSON, so json.load succeeds and .items() would then
    # raise outside the except above -- crashing on startup, the one moment
    # the watchdog most needs to keep running.
    if not isinstance(raw, dict):
        logger.warning("Watchdog state is valid JSON but not an object; ignoring")
        return WatchdogState()

    # Rebuild from the dataclass's own field list rather than naming each key.
    # Hand-enumerating silently drops any field added later: it serializes via
    # asdict() but loads back as None. This also makes retired fields harmless
    # -- a state file still carrying wifi_down_since simply loses it.
    known = {f.name for f in fields(WatchdogState)}
    return WatchdogState(**{k: v for k, v in raw.items() if k in known})


def save_state(path: str, state: WatchdogState, logger: logging.Logger) -> None:
    """Atomic write -- a truncated file would silently reset the outage clock."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            json.dump(asdict(state), fh)
        os.replace(tmp_path, path)
    except OSError as err:
        logger.error("Error saving watchdog state: %s", err)
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
