#!/usr/bin/env python3
"""Main entry point for Rachio-Flume water tracking integration."""

import asyncio
import argparse
import sys

from collector import WaterTrackingCollector
from reporter import WeeklyReporter
from lib.logger import SystemLogger, get_logger


def main():
    """Main entry point with command line interface."""
    # Setup logging first
    SystemLogger.setup(console_output=True, log_file="water_tracking.log")
    logger = get_logger(__name__)
    logger.info("Starting Rachio-Flume Water Tracking Integration")

    parser = argparse.ArgumentParser(
        description="Rachio-Flume Water Tracking Integration"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Collector commands
    collect_parser = subparsers.add_parser("collect", help="Data collection commands")
    collect_group = collect_parser.add_mutually_exclusive_group(required=True)
    collect_group.add_argument(
        "--once", action="store_true", help="Run data collection once"
    )
    collect_group.add_argument(
        "--continuous", action="store_true", help="Run continuous data collection"
    )
    collect_parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Collection interval in seconds (default: 300)",
    )
    collect_parser.add_argument(
        "--db", default="water_tracking.db", help="Database file path"
    )

    # Status command
    status_parser = subparsers.add_parser("status", help="Show current system status")
    status_parser.add_argument(
        "--db", default="water_tracking.db", help="Database file path"
    )

    # Reporting commands
    report_parser = subparsers.add_parser("report", help="Generate reports")
    report_group = report_parser.add_mutually_exclusive_group(required=True)
    report_group.add_argument(
        "--current-week", action="store_true", help="Generate current week report"
    )
    report_group.add_argument(
        "--last-week", action="store_true", help="Generate last week report"
    )
    report_group.add_argument(
        "--efficiency", action="store_true", help="Generate efficiency analysis"
    )
    report_parser.add_argument(
        "--save", action="store_true", help="Save report to file"
    )
    report_parser.add_argument(
        "--db", default="water_tracking.db", help="Database file path"
    )

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

    return 0


def run_collection(args):
    """Run data collection."""
    logger = get_logger(__name__)
    
    try:
        collector = WaterTrackingCollector(args.db, args.interval)

        if args.once:
            asyncio.run(collector.collect_once())
        elif args.continuous:
            logger.info(f"Starting continuous collection every {args.interval} seconds")
            logger.info("Press Ctrl+C to stop")
            asyncio.run(collector.run_continuous())

        return 0

    except KeyboardInterrupt:
        logger.info("Collection stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Error during collection: {e}")
        return 1


def show_status(args):
    """Show current system status."""
    logger = get_logger(__name__)
    
    try:
        collector = WaterTrackingCollector(args.db)
        status = collector.get_current_status()

        print("\n" + "=" * 50)
        print("WATER TRACKING SYSTEM STATUS")
        print("=" * 50)

        if "error" in status:
            print(f"Error: {status['error']}")
            return 1

        active_zone = status["active_zone"]
        if active_zone["zone_number"]:
            print(
                f"Active Zone: #{active_zone['zone_number']} - {active_zone['zone_name']}"
            )
        else:
            print("Active Zone: None")

        if status["current_usage_rate_gpm"]:
            print(f"Current Usage Rate: {status['current_usage_rate_gpm']:.2f} GPM")
        else:
            print("Current Usage Rate: Not available")

        print(f"Recent Sessions (24h): {status['recent_sessions_count']}")

        if status["last_rachio_collection"]:
            print(f"Last Rachio Collection: {status['last_rachio_collection']}")
        else:
            print("Last Rachio Collection: Never")

        if status["last_flume_collection"]:
            print(f"Last Flume Collection: {status['last_flume_collection']}")
        else:
            print("Last Flume Collection: Never")

        print("=" * 50 + "\n")
        return 0

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        print(f"Error getting status: {e}")
        return 1


def generate_report(args):
    """Generate reports."""
    logger = get_logger(__name__)
    
    try:
        reporter = WeeklyReporter(args.db)

        if args.current_week:
            report = reporter.generate_current_week_report()
            reporter.print_report(report)

            if args.save:
                filename = f"weekly_report_{report['week_start'][:10]}.json"
                reporter.save_report_to_file(report, filename)
                print(f"Report saved to {filename}")

        elif args.last_week:
            report = reporter.generate_last_week_report()
            reporter.print_report(report)

            if args.save:
                filename = f"weekly_report_{report['week_start'][:10]}.json"
                reporter.save_report_to_file(report, filename)
                print(f"Report saved to {filename}")

        elif args.efficiency:
            analysis = reporter.get_zone_efficiency_analysis()
            print("\n" + "=" * 60)
            print("ZONE EFFICIENCY ANALYSIS")
            print(f"Period: {analysis['analysis_period']}")
            print("=" * 60)

            if not analysis["zones"]:
                print("No zone data available for analysis.")
                return 0

            for zone_name, data in analysis["zones"].items():
                print(f"\n{zone_name}:")
                print(f"  Sessions: {data['total_sessions']}")
                print(f"  Avg flow rate: {data['average_flow_rate_gpm']} GPM")
                print(
                    f"  Water per session: {data['water_per_session_gallons']} gallons"
                )
                print(
                    f"  Duration per session: {data['duration_per_session_minutes']} minutes"
                )

            print("\n" + "=" * 60 + "\n")

        return 0

    except Exception as e:
        logger.error(f"Error generating report: {e}")
        print(f"Error generating report: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
