#!/usr/bin/env python3
import asyncio
import argparse
import sys
from typing import Optional

from august_client import AugustMonitor
from lib.logger import get_logger
from lib import Constants
from august_client import AugustClient
from lib.MyPushover import Pushover
from validate_2fa import complete_2fa


def main() -> None:
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting August Smart Lock Monitoring")

    parser = argparse.ArgumentParser(
        description="August Smart Lock monitoring and alerting"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Monitor commands
    monitor_parser = subparsers.add_parser("monitor", help="Continuous lock monitoring")
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
        help="Unlock alert threshold in minutes (default: 5)",
    )
    monitor_parser.add_argument(
        "--door-ajar-threshold",
        type=int,
        default=10,
        help="Door ajar alert threshold in minutes (default: 10)",
    )
    monitor_parser.add_argument(
        "--battery-threshold",
        type=int,
        default=20,
        help="Low battery alert threshold percentage (default: 20)",
    )

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Complete 2FA validation")
    validate_parser.add_argument("code", nargs="?", help="6-digit verification code")

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
    args: argparse.Namespace, email: str, password: str, phone: Optional[str], logger
) -> None:
    if args.command == "monitor":
        monitor = AugustMonitor(
            email=email,
            password=password,
            phone=phone,
            unlock_threshold_minutes=args.threshold,
            door_ajar_threshold_minutes=args.door_ajar_threshold,
            low_battery_threshold=args.battery_threshold,
        )

        logger.info(
            f"Starting continuous monitoring (interval: {args.interval}s, "
            f"threshold: {args.threshold}min)"
        )
        await monitor.run_continuous_monitoring(args.interval)

    elif args.command == "validate":
        logger.info("Starting 2FA validation process...")

        await complete_2fa()

    elif args.command == "test":
        if args.auth:
            logger.info("Testing August authentication...")

            client = AugustClient(email, password, phone)
            try:
                success = await client.authenticate()
                if success:
                    logger.info("✅ Authentication successful")
                    locks = await client.get_locks()
                    logger.info(f"Found {len(locks)} locks:")
                    for lock_id, lock in locks.items():
                        logger.info(f"  - {lock.device_name} ({lock_id})")
                else:
                    logger.error("❌ Authentication failed")
                    logger.info(
                        "💡 If 2FA is required, complete it in the August app first"
                    )
                    sys.exit(1)
            finally:
                await client.close()

        elif args.notification:
            logger.info("Testing pushover notification...")

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

        else:
            logger.error("Please specify --auth or --notification for test command")
            sys.exit(1)


if __name__ == "__main__":
    main()
