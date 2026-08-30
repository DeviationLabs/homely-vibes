#!/usr/bin/env python3
"""When the watchdog acts.

Isolated in its own module on purpose: this is the entire risk surface of the
feature. Everything else is plumbing that either works or throws; this is the
part where a judgement call decides whether the house reboots its own router at
3am. Keeping it a pure function of (state, now, config) means it is exhaustively
testable without a network, a clock, or a router.

The whole policy in one sentence: **if the mesh has looked broken for
``outage_threshold_secs``, reboot it; then not again for ``retry_interval_secs``.**

One clock covers both faults deliberately. Separate clocks each reset on their
own, so a Deco that alternates symptoms -- WAN dies for 40 min, recovers, radios
die for 20 min, recover -- never accumulates enough on either one and is never
rebooted, despite being visibly sick all evening. A single clock that only
resets when the mesh is *fully* healthy catches that.
"""

from dataclasses import dataclass

from lib.config import UplinkWatchdogConfig
from NetworkCheck.watchdog_state import WatchdogState


@dataclass
class ActionDecision:
    """Outcome of the policy check for one cycle."""

    act: bool
    reason: str


def _no(reason: str) -> ActionDecision:
    return ActionDecision(False, reason)


def should_act(state: WatchdogState, now: float, cfg: UplinkWatchdogConfig) -> ActionDecision:
    """Decide whether this cycle reboots the mesh.

    TODO: tune to taste. Two judgement calls are baked in:

    1. Flap handling -- ``down_since`` resets on a single healthy cycle (see
       ``UplinkWatchdog.check_once``). Fast recovery, but a Deco that flaps
       either symptom every few minutes still never accumulates enough
       downtime to trip this. Merging the two clocks narrowed that hole
       without closing it.
    2. Give-up -- with ``max_actions_per_day: 0`` it never stops, so a
       multi-day ISP outage keeps triggering reboots. Harmless while the action
       is a soft reboot; revisit if that ever changes.
    """
    if state.down_since is None:
        return _no("mesh healthy")

    elapsed = now - state.down_since
    if elapsed < cfg.outage_threshold_secs:
        return _no(f"fault {int(elapsed)}s < threshold {cfg.outage_threshold_secs}s")

    if cfg.max_actions_per_day:
        recent = state.recent_actions(now)
        if len(recent) >= cfg.max_actions_per_day:
            return _no(f"daily action budget spent ({len(recent)}/{cfg.max_actions_per_day})")

    if state.last_action_ts is None:
        return ActionDecision(True, f"fault {int(elapsed)}s, no prior action")

    since_action = now - state.last_action_ts
    if since_action < cfg.retry_interval_secs:
        return _no(f"last action {int(since_action)}s ago < retry {cfg.retry_interval_secs}s")

    return ActionDecision(True, f"fault {int(elapsed)}s, retry window open")
