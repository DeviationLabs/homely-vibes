#!/usr/bin/env python3
"""Ring device daily health check.

P1 alert when any device battery is below the threshold.
P2 (normal priority) alert when any device is offline / unreachable.
Designed for a single daily cron invocation — no polling loop, no state file.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import aiohttp
from ring_doorbell import AuthenticationError, Auth, Requires2FAError, Ring

from lib.config import RingConfig, get_config
from lib.file_lock import LockTimeoutError, acquire_lock
from lib.logger import get_logger
from lib.MyPushover import Pushover
from lib.secure_io import write_secret_atomic

USER_AGENT = "android:com.ringapp"
PUSHOVER_KEY = "Ring Security"


class RingAuthError(RuntimeError):
    """Missing / expired / rejected Ring credentials — needs re-auth, not urgent."""


def _load_token(path: str) -> Optional[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())  # type: ignore[no-any-return]


def _save_token(path: str, token: dict[str, Any]) -> None:
    write_secret_atomic(path, token)


async def _auth_flow(username: str, password: str, token_file: str) -> None:
    """Interactive first-time login. Writes token to token_file."""
    auth = Auth(USER_AGENT)
    try:
        token = await auth.async_fetch_token(username, password)
    except Requires2FAError:
        code = input("Ring 2FA code (from SMS/email): ").strip()
        token = await auth.async_fetch_token(username, password, code)
    _save_token(token_file, token)


# Injectable factory so tests can supply a fake Ring client.
RingFactory = Callable[[aiohttp.ClientSession, dict[str, Any], str], Awaitable[Ring]]


async def _default_ring_factory(
    session: aiohttp.ClientSession, token: dict[str, Any], token_file: str
) -> Ring:
    auth = Auth(
        USER_AGENT,
        token,
        lambda t: _save_token(token_file, t),
        http_client_session=session,
    )
    ring = Ring(auth)
    await ring.async_update_data()
    return ring


async def check_devices(
    cfg: RingConfig,
    logger: logging.Logger,
    ring_factory: RingFactory = _default_ring_factory,
) -> tuple[list[str], list[str]]:
    """Return (low_battery_lines, offline_names)."""
    token = _load_token(cfg.token_file)
    if not token:
        raise RingAuthError(
            f"No Ring token at {cfg.token_file}. "
            "Run: uv run python RingSecurity/ring_manager.py auth"
        )

    low: list[str] = []
    offline: list[str] = []

    async with aiohttp.ClientSession() as session:
        try:
            ring = await ring_factory(session, token, cfg.token_file)
        except AuthenticationError as e:
            raise RingAuthError(f"Ring auth rejected: {e}") from e
        for dev in ring.devices().all_devices:
            batt_raw = dev.battery_life
            # Ring occasionally returns battery_life as a string on certain
            # device types; coerce defensively. Wired devices report None or 0
            # (library flattens Ring's null inconsistently) — filter both. A
            # real battery device dies at ~5%, never sustains 0, and the
            # offline check catches truly dead cells anyway.
            try:
                # float() first — handles "15.5" strings that int() alone rejects.
                batt = int(float(batt_raw)) if batt_raw is not None else None
            except (TypeError, ValueError):
                batt = None
            if batt is not None and 0 < batt < cfg.battery_threshold_pct:
                low.append(f"{dev.name}: {batt}%")

            try:
                await dev.async_update_health_data()
                sig = getattr(dev, "wifi_signal_category", None)
                if sig is None or str(sig).lower() == "offline":
                    offline.append(dev.name)
            except Exception as e:
                logger.warning(f"Health fetch failed for {dev.name}: {e}")
                offline.append(dev.name)

    return low, offline


def notify(pushover: Pushover, low: list[str], offline: list[str], logger: logging.Logger) -> None:
    if low:
        body = "\n".join(low)
        logger.info(f"Low battery alert: {body}")
        pushover.send_message(body, title="Ring: Low Battery", priority=1)
    if offline:
        body = "\n".join(offline)
        logger.info(f"Offline alert: {body}")
        pushover.send_message(body, title="Ring: Device Offline", priority=0)
    if not low and not offline:
        logger.info("All Ring devices healthy.")


def main() -> None:
    logger = get_logger(__name__)
    parser = argparse.ArgumentParser(description="Ring daily battery + offline check")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Run daily health check (for cron)")
    sub.add_parser("auth", help="Interactive first-time 2FA login")
    args = parser.parse_args()

    cfg = get_config()

    if args.command == "auth":
        username = cfg.ring.username or input("Ring username: ").strip()
        password = cfg.ring.password or getpass.getpass("Ring password: ")
        asyncio.run(_auth_flow(username, password, cfg.ring.token_file))
        logger.info(f"Token written to {cfg.ring.token_file}")
        return

    pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens[PUSHOVER_KEY])
    try:
        # Serialize against RingBeams (Node sidecar via beams_manager) — both
        # read/write cfg.ring.token_file and Ring OAuth rotates refresh_token
        # on every use. Held for the whole ring session (refresh happens
        # inside ring-doorbell, not at a call site we control).
        with acquire_lock(cfg.ring.token_file):
            low, offline = asyncio.run(check_devices(cfg.ring, logger))
        notify(pushover, low, offline, logger)
    except LockTimeoutError as e:
        logger.error(f"Ring token lock timeout: {e}")
        pushover.send_message(str(e), title="Ring: Token Lock Timeout", priority=1)
        sys.exit(1)
    except RingAuthError as e:
        logger.error(f"Ring auth failure: {e}")
        pushover.send_message(str(e), title="Ring: Auth Required", priority=0)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Ring check failed: {e}")
        pushover.send_message(str(e), title="Ring Check Error", priority=1)
        sys.exit(1)


if __name__ == "__main__":
    main()
