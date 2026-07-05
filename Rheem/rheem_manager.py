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
    {"alerted": {"<serial>": true/false}}
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Protocol

from Rheem.rheem_client import RheemAPIError, RheemAuthError, RheemClient, WaterHeaterStatus
from lib.config import Config, get_config
from lib.logger import get_logger
from lib.MyPushover import Pushover


_AVAILABILITY_LABEL = {0: "empty", 33: "1/3rd full", 66: "2/3rd full", 100: "full"}


class Notifier(Protocol):
    """Send-only notification surface (satisfied by Pushover or test fakes)."""

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool: ...


def _label(avail: int) -> str:
    return _AVAILABILITY_LABEL.get(avail, f"{avail}%")


class RheemMonitor:
    """Polls water heaters and fires/clears low-hot-water alerts."""

    def __init__(
        self,
        client: RheemClient,
        pushover: Notifier,
        logger: logging.Logger,
        state_file: str,
        low_threshold: int = 33,
        mid_threshold: int = 66,
    ) -> None:
        self.client = client
        self.pushover = pushover
        self.logger = logger
        self.state_file = state_file
        self.low_threshold = low_threshold
        self.mid_threshold = mid_threshold
        self.alerted: dict[str, bool] = {}
        self._load_state()

    def _load_state(self) -> None:
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
                self.alerted = state.get("alerted", {})
            self.logger.debug("Loaded Rheem monitor state from %s", self.state_file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.debug("No existing Rheem state file; starting fresh")

    def _save_state(self) -> None:
        try:
            with open(self.state_file, "w") as f:
                json.dump({"alerted": self.alerted}, f)
            self.logger.debug("Saved Rheem monitor state to %s", self.state_file)
        except OSError as e:
            self.logger.error("Error saving Rheem state: %s", e)

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

        current_serials = {h.serial_number for h in heaters}
        for status in heaters:
            self._process(status)

        # Prune devices that no longer appear.
        self.alerted = {s: v for s, v in self.alerted.items() if s in current_serials}
        self._save_state()
        return heaters

    def _process(self, status: WaterHeaterStatus) -> None:
        if not status.connected:
            self.logger.debug("%s disconnected; skipping", status.name)
            return
        if status.availability is None:
            self.logger.debug("%s does not report availability; skipping", status.name)
            return

        is_alerted = self.alerted.get(status.serial_number, False)

        if status.availability <= self.low_threshold and not is_alerted:
            msg = (
                f"Hot water low: {status.name} at {_label(status.availability)} "
                f"({status.availability}%)"
            )
            self.pushover.send_message(msg, title="Rheem Low Hot Water", priority=1)
            self.alerted[status.serial_number] = True
            self.logger.warning("Fired low-hot-water alert: %s", msg)

        elif status.availability >= self.mid_threshold and is_alerted:
            msg = (
                f"Hot water recovered: {status.name} at {_label(status.availability)} "
                f"({status.availability}%)"
            )
            self.pushover.send_message(msg, title="Rheem Hot Water Recovered", priority=-1)
            self.alerted[status.serial_number] = False
            self.logger.info("Cleared low-hot-water alert: %s", msg)

    async def run_continuous(self, poll_seconds: int) -> None:
        self.logger.info("Starting continuous Rheem monitoring (interval: %ds)", poll_seconds)
        while True:
            await self.check_once()
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
        low_threshold=cfg.rheem.low_threshold,
        mid_threshold=cfg.rheem.mid_threshold,
    )


async def _monitor(args: argparse.Namespace, cfg: Config, logger: logging.Logger) -> None:
    monitor = _build_monitor(cfg, logger)
    await monitor.run_continuous(args.poll_secs)


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

    monitor_parser = subparsers.add_parser("monitor", help="Continuous monitoring")
    monitor_parser.add_argument(
        "--poll-secs",
        type=int,
        default=None,
        help="Check interval in seconds (default: from config)",
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
