#!/usr/bin/env python3
"""Ring Beams / Alarm daily health check.

Spawns a Node.js sidecar (fetch_status.js) that uses ring-client-api to
pull device state via Ring's socket.io channel — the only way to get
battery for Beams motion sensors and Alarm contact/motion sensors.

P1 alert: any device below the battery threshold, OR batteryStatus == "warn".
P2 alert: any device with tamperStatus == "tamper".
P2 alert: sidecar auth failure (needs re-auth).

Skips devices with batteryLevel == null (wired base stations, adapters,
hubs). `faulted: true` on contact sensors just means "door open now" —
ignored.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lib.config import RingBeamsConfig, get_config
from lib.logger import get_logger
from lib.MyPushover import Pushover

PUSHOVER_KEY = "Ring Security"
WIRED_BATTERY_STATUSES = {"none", "charging", "charged"}


class BeamsAuthError(RuntimeError):
    """Sidecar refresh token missing / expired / rejected."""


@dataclass
class DeviceRecord:
    name: str
    device_type: str
    location: str
    battery: Optional[int]
    battery_status: Optional[str]
    tamper: Optional[str]


def _resolve_node() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "`node` not found on PATH. Install Node.js (e.g. `brew install node`) "
            "and ensure PATH is set correctly in cron."
        )
    return node


def run_sidecar(
    cfg: RingBeamsConfig,
    logger: logging.Logger,
    *,
    node_path: Optional[str] = None,
    script_path: Optional[str] = None,
) -> tuple[list[DeviceRecord], list[str]]:
    """Invoke fetch_status.js. Returns (devices, per-location errors).

    Per-location errors are surfaced (not raised) so a partial failure never
    masks itself as "all healthy" — the caller pushes them to Pushover at P1.
    """
    node = node_path or _resolve_node()
    script = script_path or str(Path(__file__).resolve().parent / "fetch_status.js")
    token_file = cfg.token_file
    if not Path(token_file).exists():
        raise BeamsAuthError(
            f"No Ring token at {token_file}. Run "
            "`uv run python RingSecurity/ring_manager.py auth` first "
            "(RingBeams reuses the RingSecurity token)."
        )

    env = os.environ.copy()
    env["RING_BEAMS_TOKEN_FILE"] = token_file

    logger.info(f"Spawning node sidecar: {node} {script}")
    proc = subprocess.run(
        [node, script],
        env=env,
        capture_output=True,
        text=True,
        timeout=cfg.sidecar_timeout_seconds,
    )
    if proc.returncode != 0:
        # Sidecar prints JSON error on stderr on known-failure exits (1..3).
        try:
            err = json.loads(proc.stderr.strip().splitlines()[-1])
            msg = err.get("error", proc.stderr)
        except Exception:
            msg = proc.stderr.strip() or "sidecar failed with no stderr"
        # Sidecar exit-code contract (see fetch_status.js):
        #   1  auth/list-locations failure (bad or missing token)
        #   3  token file unreadable
        #   4  post-auth unhandled exception (parsing bug, etc.)
        # 1 and 3 → auth class; 4 is generic (must not misroute to "re-auth").
        if proc.returncode in (1, 3):
            raise BeamsAuthError(msg)
        raise RuntimeError(f"sidecar exit={proc.returncode}: {msg}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"sidecar produced non-JSON stdout: {e}") from e

    out: list[DeviceRecord] = []
    for d in payload.get("devices", []):
        out.append(
            DeviceRecord(
                name=d.get("name", "<unnamed>"),
                device_type=d.get("deviceType", ""),
                location=d.get("locationName", ""),
                battery=d.get("batteryLevel"),
                battery_status=d.get("batteryStatus"),
                tamper=d.get("tamperStatus"),
            )
        )
    errors = list(payload.get("errors", []) or [])
    return out, errors


def classify(devices: list[DeviceRecord], threshold_pct: int) -> tuple[list[str], list[str]]:
    """Split devices into (low_battery_msgs, tamper_msgs)."""
    low: list[str] = []
    tamper: list[str] = []
    for d in devices:
        # Skip mains-powered / recharging: batteryLevel is None or status is wired.
        if d.battery is None:
            continue
        if d.battery_status in WIRED_BATTERY_STATUSES:
            continue

        # Low battery: Ring's own "warn" signal OR our threshold. Coerce str→int.
        try:
            batt_int = int(float(d.battery))
        except (TypeError, ValueError):
            batt_int = None
        if d.battery_status == "warn" or (batt_int is not None and batt_int < threshold_pct):
            batt_display = batt_int if batt_int is not None else d.battery
            low.append(f"{d.name}: {batt_display}%")

        if d.tamper == "tamper":
            tamper.append(f"{d.name} (tampered)")
    return low, tamper


def notify(
    pushover: Pushover,
    low: list[str],
    tamper: list[str],
    errors: list[str],
    logger: logging.Logger,
) -> None:
    if low:
        body = "\n".join(low)
        logger.info(f"Low battery alert: {body}")
        pushover.send_message(body, title="Ring Beams/Alarm: Low Battery", priority=1)
    if tamper:
        body = "\n".join(tamper)
        logger.info(f"Tamper alert: {body}")
        pushover.send_message(body, title="Ring Beams/Alarm: Tamper", priority=0)
    if errors:
        # Partial-location failure — coverage was incomplete, mustn't look healthy.
        body = "\n".join(errors)
        logger.error(f"Sidecar partial failure: {body}")
        pushover.send_message(body, title="Ring Beams/Alarm: Partial Sidecar Failure", priority=1)
    if not low and not tamper and not errors:
        logger.info("All Ring Beams/Alarm sensors healthy.")


def main() -> None:
    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(
        description="Ring Beams + Alarm daily health check via Node sidecar"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Run daily health check (for cron)")
    parser.parse_args()

    cfg = get_config()
    pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens[PUSHOVER_KEY])
    try:
        devices, errors = run_sidecar(cfg.ring_beams, logger)
        logger.info(f"Fetched {len(devices)} devices from sidecar ({len(errors)} location errors)")
        low, tamper = classify(devices, cfg.ring_beams.battery_threshold_pct)
        notify(pushover, low, tamper, errors, logger)
    except BeamsAuthError as e:
        logger.error(f"Ring Beams auth failure: {e}")
        pushover.send_message(str(e), title="Ring Beams: Auth Required", priority=0)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Ring Beams check failed: {e}")
        pushover.send_message(str(e), title="Ring Beams: Error", priority=1)
        sys.exit(1)


if __name__ == "__main__":
    main()
