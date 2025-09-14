#!/usr/bin/env python3

import asyncio
import argparse
import sys

from august_client import AugustMonitor
from lib.logger import get_logger
from lib import Constants


def main() -> None:
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting August Smart Lock Monitoring")

    parser = argparse.ArgumentParser(
        description="August Smart Lock monitoring and alerting"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Monitor commands
    monitor_parser = subparsers.add_parser("monitor", help="Lock monitoring commands")
    monitor_group = monitor_parser.add_mutually_exclusive_group(required=True)
    monitor_group.add_argument(
        "--once", action="store_true", help="Check locks once and exit"
    )
    monitor_group.add_argument(
        "--continuous", action="store_true", help="Run continuous monitoring"
    )
    monitor_parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Check interval in seconds (default: 60)",
    )
    monitor_parser.add_argument(
        "--threshold",
        type=int,
        default=5,
        help="Alert threshold in minutes (default: 5)",
    )

    # Status command
    subparsers.add_parser("status", help="Show current lock status")

    # Test command
    test_parser = subparsers.add_parser("test", help="Test commands")
    test_parser.add_argument(
        "--auth", action="store_true", help="Test authentication only"
    )
    test_parser.add_argument(
        "--notification", action="store_true", help="Test pushover notification"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Get August credentials from Constants
    if not hasattr(Constants, "AUGUST_EMAIL") or not hasattr(
        Constants, "AUGUST_PASSWORD"
    ):
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


async def _run_command(
    args: argparse.Namespace, email: str, password: str, phone: str, logger
) -> None:
    if args.command == "monitor":
        monitor = AugustMonitor(
            email=email,
            password=password,
            phone=phone,
            unlock_threshold_minutes=args.threshold,
        )

        if args.once:
            logger.info("Running single lock check...")
            await monitor.check_locks()
            logger.info("Lock check completed")

        elif args.continuous:
            logger.info(
                f"Starting continuous monitoring (interval: {args.interval}s, "
                f"threshold: {args.threshold}min)"
            )
            await monitor.run_continuous_monitoring(args.interval)

    elif args.command == "status":
        logger.info("Getting current lock status...")
        monitor = AugustMonitor(email=email, password=password, phone=phone)
        status_report = await monitor.get_status_report()
        print(status_report)

    elif args.command == "test":
        if args.auth:
            logger.info("Testing August authentication...")
            from august_client import AugustClient

            client = AugustClient(email, password, phone)
            success = await client.authenticate()
            if success:
                logger.info("✅ Authentication successful")
                locks = await client.get_locks()
                logger.info(f"Found {len(locks)} locks:")
                for lock_id, lock in locks.items():
                    logger.info(f"  - {lock.device_name} ({lock_id})")
            else:
                logger.error("❌ Authentication failed")
                sys.exit(1)

        elif args.notification:
            logger.info("Testing pushover notification...")
            from lib.MyPushover import Pushover

            pushover = Pushover(
                Constants.PUSHOVER_USER, Constants.PUSHOVER_DEFAULT_TOKEN
            )
            try:
                pushover.send_message(
                    "This is a test notification from August Lock Monitor",
                    title="🔓 August Test Alert",
                )
                logger.info("✅ Notification sent successfully")
            except Exception as e:
                logger.error(f"❌ Notification failed: {e}")
                sys.exit(1)


if __name__ == "__main__":
    main()
