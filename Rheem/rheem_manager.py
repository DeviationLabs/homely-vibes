#!/usr/bin/env python3
"""Rheem EcoNet water heater monitor.

Alerts when available hot water is low and clears the alert when it recovers
to mid. Uses hysteresis with persisted state so we don't re-alert every poll
or flap between adjacent levels.

Availability levels (from the tank):
    0   = empty
    33  = "1/3rd full"   -> LOW  (fire P1 alert)
    66  = "2/3rd full"   -> MID  (send P-1 clear, reset alert state)
    100 = full

State is persisted to {logging_dir}/rheem_monitor_state.json as
    {"alerted": {"<serial>": "p1"|"p2"}}

Deployment: cron runs `check` every few minutes (run-once per tick —
fresh auth each run, free crash recovery, matches the repo cron convention).
`monitor` is a foreground/dev alternative. `test` is a one-shot status dump.
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from Rheem.rheem_client import RheemAPIError, RheemAuthError, RheemClient, WaterHeaterStatus
from lib.config import Config, get_config
from lib.logger import get_logger
from lib.MyPushover import Pushover
from lib.notifications import Notifier


_AVAILABILITY_LABEL = {0: "empty", 33: "1/3rd full", 66: "2/3rd full", 100: "full"}


def _label(avail: int) -> str:
    return _AVAILABILITY_LABEL.get(avail, f"{avail}%")


def _setpoint(status: WaterHeaterStatus) -> str:
    """Format the setpoint for inclusion in alert messages, or 'unknown'."""
    return f"{status.set_point}°F" if status.set_point is not None else "unknown"


class RheemMonitor:
    """Polls water heaters and fires/clears low-hot-water alerts."""

    def __init__(
        self,
        client: RheemClient,
        pushover: Notifier,
        logger: logging.Logger,
        state_file: str,
        empty_threshold: int = 0,
        low_threshold: int = 33,
        mid_threshold: int = 66,
    ) -> None:
        self.client = client
        self.pushover = pushover
        self.logger = logger
        self.state_file = state_file
        self.empty_threshold = empty_threshold
        self.low_threshold = low_threshold
        self.mid_threshold = mid_threshold
        # Per-device current alert tier: "p1" (low) or "p2" (empty).
        # Absent key = not alerted. Cleared only on recovery to >= mid_threshold.
        self.alerted: dict[str, str] = {}
        # Per-device last observed setpoint, used to detect a raise that would
        # explain a sudden drop in availability (tank reheating to new target).
        self.setpoints: dict[str, int] = {}
        self._load_state()

    def _load_state(self) -> None:
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
                self.alerted = state.get("alerted", {})
                self.setpoints = state.get("setpoints", {})
            self.logger.debug("Loaded Rheem monitor state from %s", self.state_file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.debug("No existing Rheem state file; starting fresh")

    def _save_state(self) -> None:
        # Atomic write via tmp + os.replace so an interrupt mid-write can't
        # truncate the state file (which would silently reset all alert state
        # and re-fire P1/P2 alerts on the next cycle).
        tmp_path = self.state_file + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump({"alerted": self.alerted, "setpoints": self.setpoints}, f)
            os.replace(tmp_path, self.state_file)
            self.logger.debug("Saved Rheem monitor state to %s", self.state_file)
        except OSError as e:
            self.logger.error("Error saving Rheem state: %s", e)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    async def check_once(self) -> list[WaterHeaterStatus]:
        """Run one polling cycle. Returns the statuses observed this cycle."""
        try:
            heaters = await self.client.get_water_heaters()
        except RheemAuthError as e:
            self.pushover.send_message(
                f"Rheem auth failed: {e}",
                title="Rheem Auth",
                priority=0,
            )
            self.logger.error("Rheem auth failed: %s", e)
            return []
        except RheemAPIError as e:
            self.pushover.send_message(
                f"Rheem API error: {e}",
                title="Rheem Error",
                priority=0,
            )
            self.logger.error("Rheem API error: %s", e)
            return []
        except Exception as e:
            # pyeconet only wraps PyeconetError subclasses; transient network
            # errors (aiohttp.ClientError, asyncio.TimeoutError, OSError) are
            # re-raised raw. Don't let them kill the run_continuous loop.
            self.logger.error("Transient error during Rheem check: %s", e)
            return []

        current_serials = {h.serial_number for h in heaters}
        for status in heaters:
            self._process(status)

        # Prune devices that no longer appear.
        self.alerted = {s: v for s, v in self.alerted.items() if s in current_serials}
        self.setpoints = {s: v for s, v in self.setpoints.items() if s in current_serials}
        self._save_state()
        return heaters

    def _process(self, status: WaterHeaterStatus) -> None:
        if not status.connected:
            self.logger.debug("%s disconnected; skipping", status.name)
            return
        avail = status.availability
        if avail is None:
            self.logger.debug("%s does not report availability; skipping", status.name)
            return

        # Record the current setpoint for next cycle's comparison before any
        # early return so we always have a baseline to detect a raise.
        previous_setpoint = self.setpoints.get(status.serial_number)
        if status.set_point is not None:
            self.setpoints[status.serial_number] = status.set_point
        setpoint_raised = (
            status.set_point is not None
            and previous_setpoint is not None
            and status.set_point > previous_setpoint
        )

        active_tier = self.alerted.get(status.serial_number)

        # Clear only on explicit recovery to >= mid_threshold (not merely
        # "above low" — that would let a level between low and mid prematurely
        # clear an active alert). mid_threshold is the configured recovery gate.
        if active_tier is not None and avail >= self.mid_threshold:
            msg = f"Hot water recovered: {status.name} at {_label(avail)} ({avail}%), setpoint {_setpoint(status)}"
            self.pushover.send_message(msg, title="Rheem Hot Water Recovered", priority=-1)
            del self.alerted[status.serial_number]
            self.logger.info("Cleared hot-water alert: %s", msg)
            return

        current_tier = self._tier_for(avail)
        if current_tier is None:
            # In the dead zone (low_threshold < avail < mid_threshold): hold
            # any active alert without re-firing; no-op if not alerted.
            return

        # In a low zone (empty or 1/3rd). Decide whether to fire/escalate.
        # Suppress when the setpoint was raised since the last check: the drop
        # in availability is expected while the tank reheats to the new target.
        if active_tier is None:
            if setpoint_raised:
                self.logger.info(
                    "Suppressing %s alert for %s: setpoint raised %s->%s, "
                    "low availability likely due to reheating",
                    current_tier,
                    status.name,
                    previous_setpoint,
                    status.set_point,
                )
            else:
                self._fire(status, avail, current_tier)
        elif current_tier == "p2" and active_tier == "p1":
            # Escalate low -> empty (unless setpoint was raised).
            if setpoint_raised:
                self.logger.info(
                    "Suppressing p2 escalation for %s: setpoint raised %s->%s, "
                    "low availability likely due to reheating",
                    status.name,
                    previous_setpoint,
                    status.set_point,
                )
            else:
                self._fire(status, avail, current_tier)
        # Same tier, or recovering empty->low: no re-alert (clear at mid resets).

    def _tier_for(self, availability: int) -> str | None:
        """Return the alert tier for an availability level, or None if healthy."""
        if availability <= self.empty_threshold:
            return "p2"
        if availability <= self.low_threshold:
            return "p1"
        return None

    def _fire(self, status: WaterHeaterStatus, avail: int, tier: str) -> None:
        priority = 2 if tier == "p2" else 1
        label = "empty" if tier == "p2" else "low"
        msg = f"Hot water {label}: {status.name} at {_label(avail)} ({avail}%), setpoint {_setpoint(status)}"
        title = "Rheem Hot Water Empty" if tier == "p2" else "Rheem Low Hot Water"
        self.pushover.send_message(msg, title=title, priority=priority)
        self.alerted[status.serial_number] = tier
        self.logger.warning("Fired %s hot-water alert: %s", tier.upper(), msg)

    async def run_continuous(self, poll_seconds: int) -> None:
        self.logger.info("Starting continuous Rheem monitoring (interval: %ds)", poll_seconds)
        while True:
            try:
                await self.check_once()
            except Exception as e:
                # Safety net: check_once handles known/transient errors, but a
                # bug in _process/_save_state must not kill the monitor either.
                self.logger.error("Unexpected error in Rheem poll cycle: %s", e)
            await asyncio.sleep(poll_seconds)


def _build_monitor(cfg: Config, logger: logging.Logger) -> RheemMonitor:
    client = RheemClient(cfg.rheem.email, cfg.rheem.password)
    pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens["Rheem"])
    state_file = f"{cfg.paths.logging_dir}/rheem_monitor_state.json"
    return RheemMonitor(
        client=client,
        pushover=pushover,
        logger=logger,
        state_file=state_file,
        empty_threshold=cfg.rheem.empty_threshold,
        low_threshold=cfg.rheem.low_threshold,
        mid_threshold=cfg.rheem.mid_threshold,
    )


async def _monitor(args: argparse.Namespace, cfg: Config, logger: logging.Logger) -> None:
    monitor = _build_monitor(cfg, logger)
    await monitor.run_continuous(args.poll_secs)


async def _check(args: argparse.Namespace, cfg: Config, logger: logging.Logger) -> None:
    """One polling cycle for cron: runs the alert state machine, then exits.

    No Pushover status summary (unlike `test`) — alerts fire from the state
    machine only when a threshold is crossed. Exit 0 on success so cron stays
    quiet; non-zero exits surface in the cron log on real failures.
    """
    monitor = _build_monitor(cfg, logger)
    heaters = await monitor.check_once()
    logger.info(
        "Rheem check complete: %d heater(s), %d alerted",
        len(heaters),
        len(monitor.alerted),
    )


async def _test(args: argparse.Namespace, cfg: Config, logger: logging.Logger) -> None:
    monitor = _build_monitor(cfg, logger)
    heaters = await monitor.check_once()
    if not heaters:
        logger.warning("No water heaters reported this cycle")
        return
    lines = []
    for h in heaters:
        avail = "N/A" if h.availability is None else f"{h.availability}% ({_label(h.availability)})"
        lines.append(
            f"{h.name}: avail={avail}, running={h.running}, "
            f"set_point={h.set_point}, connected={h.connected}"
        )
    summary = "\n".join(lines)
    logger.info("Rheem status:\n%s", summary)
    monitor.pushover.send_message(summary, title="Rheem Status", priority=-1)


async def _run_command(args: argparse.Namespace, cfg: Config, logger: logging.Logger) -> None:
    if args.command == "monitor":
        await _monitor(args, cfg, logger)
    elif args.command == "check":
        await _check(args, cfg, logger)
    elif args.command == "test":
        await _test(args, cfg, logger)


def main() -> None:
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting Rheem EcoNet Water Heater Monitoring")

    parser = argparse.ArgumentParser(
        description="Rheem EcoNet water heater monitoring and alerting"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    monitor_parser = subparsers.add_parser(
        "monitor", help="Foreground continuous monitoring (dev; cron uses `check`)"
    )
    monitor_parser.add_argument(
        "--poll-secs",
        type=int,
        default=None,
        help="Check interval in seconds (default: from config)",
    )

    _ = subparsers.add_parser(
        "check", help="One polling cycle (cron): alert state machine, then exit"
    )

    _ = subparsers.add_parser("test", help="One-shot status check + Pushover summary")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cfg = get_config()
    if not cfg.rheem.email or not cfg.rheem.password:
        logger.error("Rheem credentials not found in config")
        logger.error("Add rheem.email and rheem.password to config/local.yaml")
        sys.exit(1)

    if args.command == "monitor" and args.poll_secs is None:
        args.poll_secs = cfg.rheem.poll_seconds

    try:
        asyncio.run(_run_command(args, cfg, logger))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
