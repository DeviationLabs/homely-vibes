#!/usr/bin/env python3
"""Main entry point for Rachio-Flume water tracking integration."""

import asyncio
import argparse
import sys
from time import sleep
from collector import WaterTrackingCollector
from lib.MyPushover import Pushover
from reporter import WeeklyReporter
from lib.logger import get_logger
from lib import Constants
from datetime import datetime, timedelta

# Create default database path using Constants.LOGGING_DIR
DB_PATH = Constants.LOGGING_DIR + "/water_tracking.db"
pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS.get("RachioFlume", Constants.PUSHOVER_DEFAULT_TOKEN))


def main():
    """Main entry point with command line interface."""
    # Setup logging first
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting Rachio-Flume Water Tracking Integration")

    parser = argparse.ArgumentParser(
        description="Rachio-Flume Water Tracking Integration"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Collector commands
    collect_parser = subparsers.add_parser("collect", help="Data collection commands")
    collect_parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Collection interval in seconds (default: 300)",
    )

    # Status command
    subparsers.add_parser("status", help="Show current system status")

    # Reporting commands
    report_parser = subparsers.add_parser("report", help="Generate period reports")
    report_parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date for report (YYYY-MM-DD format, defaults to today)",
    )
    report_parser.add_argument(
        "--lookback",
        type=int,
        default=7,
        help="Number of days to look back from end date (default: 7)",
    )
    report_parser.add_argument(
        "--email", action="store_true", help="Send report via email"
    )

    # Summary command
    subparsers.add_parser("summary", help="Generate efficiency analysis")


    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "collect":
        return run_collection(args)
    elif args.command == "status":
        return show_status(args)
    elif args.command == "report":
        return generate_report(args)
    elif args.command == "summary":
        return generate_summary_report(args)

    return 0


def run_collection(args):
    """Run data collection."""
    logger = get_logger(__name__)

    try:
        collector = WaterTrackingCollector(DB_PATH, args.interval)

        logger.info(f"Starting continuous collection every {args.interval} seconds")
        logger.info("Press Ctrl+C to stop")
        asyncio.run(collector.run_continuous())

    except KeyboardInterrupt:
        logger.info("Collection stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Error during collection: {e}")
        pushover.send_message(f"Error during collection: {e}", title="RachioFlume Error", priority=2)
        sleep(3600)  ## cooldown for an hour. 
        return 1


def show_status(args):
    """Show current system status."""
    logger = get_logger(__name__)

    try:
        collector = WaterTrackingCollector(DB_PATH)
        status = collector.get_current_status()

        logger.info("\n" + "=" * 50)
        logger.info("WATER TRACKING SYSTEM STATUS")
        logger.info("=" * 50)

        if "error" in status:
            logger.error(f"Error: {status['error']}")
            return 1

        active_zone = status["active_zone"]
        if active_zone["zone_number"]:
            logger.info(
                f"Active Zone: #{active_zone['zone_number']} - {active_zone['zone_name']}"
            )
        else:
            logger.info("Active Zone: None")

        if status["current_usage_rate_gpm"]:
            logger.info(
                f"Current Usage Rate: {status['current_usage_rate_gpm']:.2f} GPM"
            )
        else:
            logger.info("Current Usage Rate: Not available")

        logger.info(f"Recent Sessions (24h): {status['recent_sessions_count']}")

        if status["last_rachio_collection"]:
            logger.info(f"Last Rachio Collection: {status['last_rachio_collection']}")
        else:
            logger.info("Last Rachio Collection: Never")

        if status["last_flume_collection"]:
            logger.info(f"Last Flume Collection: {status['last_flume_collection']}")
        else:
            logger.info("Last Flume Collection: Never")

        logger.info("=" * 50 + "\n")
        return 0

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return 1


def generate_report(args):
    """Generate reports."""
    logger = get_logger(__name__)

    try:
        reporter = WeeklyReporter(DB_PATH)

        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
        start_date = end_date - timedelta(days=args.lookback)
        report = reporter.generate_period_report_with_dates(start_date, end_date)
        reporter.print_report(report)

        if args.email:
            reporter.email_report(report, alert=False)
            logger.info("Report emailed")

        return 0

    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return 1


def generate_summary_report(args):
    """Generate efficiency analysis reports."""
    logger = get_logger(__name__)

    try:
        reporter = WeeklyReporter(DB_PATH)

        analysis = reporter.get_zone_efficiency_analysis()
        reporter.print_efficiency_analysis(analysis)

        return 0

    except Exception as e:
        logger.error(f"Error generating summary report: {e}")
        return 1




if __name__ == "__main__":
    sys.exit(main())
