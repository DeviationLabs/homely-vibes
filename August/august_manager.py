#!/usr/bin/env python3
import asyncio
import argparse
import sys
from typing import Optional
import logging

from .august_client import AugustMonitor, AugustClient
from lib.logger import get_logger
from lib import Constants
from lib.MyPushover import Pushover
from .validate_2fa import complete_2fa

pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["August"])


async def _test(
    args: argparse.Namespace,
    email: str,
    password: str,
    phone: Optional[str],
    logger: logging.Logger,
) -> None:
    client = AugustClient(Constants.AUGUST_EMAIL, Constants.AUGUST_PASSWORD)
    message = ""
    try:
        statuses = await client.get_all_lock_statuses()
        for _, status in statuses.items():
            message += f"{status.lock_name}: {status.battery_level}%\n"
        pushover.send_message(message, title="August Battery Status", priority=0)
    except Exception as e:
        pushover.send_message(
            f"Error initializing August client: {e}",
            title="August Battery Status",
            priority=2,
        )
    finally:
        await client.close()


async def _run_command(
    args: argparse.Namespace,
    email: str,
    password: str,
    phone: Optional[str],
    logger: logging.Logger,
) -> None:
    if args.command == "monitor":
        monitor = AugustMonitor(
            email=email,
            password=password,
            phone=phone,
            unlock_threshold_minutes=args.lock_mins,
            ajar_threshold_minutes=args.ajar_mins,
            battery_threshold_pct=args.battery_pct,
        )

        logger.info(
            f"Starting continuous monitoring (interval: {args.poll_secs}s, "
            f"threshold: {args.lock_mins}min)"
        )
        await monitor.run_continuous_monitoring(args.poll_secs)

    elif args.command == "validate":
        logger.info("Starting 2FA validation process...")

        await complete_2fa()

    elif args.command == "test":
        await _test(args, email, password, phone, logger)


def main() -> None:
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting August Smart Lock Monitoring")

    parser = argparse.ArgumentParser(description="August Smart Lock monitoring and alerting")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Monitor commands
    monitor_parser = subparsers.add_parser("monitor", help="Continuous lock monitoring")
    monitor_parser.add_argument(
        "--poll-secs",
        type=int,
        default=60,
        help="Check interval in seconds (default: 60)",
    )
    monitor_parser.add_argument(
        "--lock-mins",
        type=int,
        default=5,
        help="Unlock alert threshold in minutes (default: 5)",
    )
    monitor_parser.add_argument(
        "--ajar-mins",
        type=int,
        default=10,
        help="Door ajar alert threshold in minutes (default: 10)",
    )
    monitor_parser.add_argument(
        "--battery-pct",
        type=int,
        default=20,
        help="Low battery alert threshold percentage (default: 20)",
    )

    # Validate command
    _ = subparsers.add_parser("validate", help="Complete 2FA validation")

    # Test command
    _ = subparsers.add_parser("test", help="Test commands")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Get August credentials from Constants
    if not hasattr(Constants, "AUGUST_EMAIL") or not hasattr(Constants, "AUGUST_PASSWORD"):
        logger.error("August credentials not found in Constants.py")
        logger.error("Please add AUGUST_EMAIL and AUGUST_PASSWORD to Constants.py")
        sys.exit(1)

    email = Constants.AUGUST_EMAIL
    password = Constants.AUGUST_PASSWORD
    phone = getattr(Constants, "AUGUST_PHONE", None)

    try:
        asyncio.run(_run_command(args, email, password, phone, logger))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
