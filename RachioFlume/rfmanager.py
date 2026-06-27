#!/usr/bin/env python3
"""Main entry point for Rachio-Flume water tracking integration."""

import asyncio
import argparse
import sys
from time import sleep
from RachioFlume.alert_engine import AlertEngine
from RachioFlume.alert_rules import (
    get_controller_zone_thresholds,
    load_rules_from_config,
    load_zone_thresholds_from_config,
)
from RachioFlume.collector import WaterTrackingCollector
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.flume_client import FlumeClient
from RachioFlume.hose_timer_processor import HoseTimerProcessor
from RachioFlume.rachio_client import RachioClient
from RachioFlume.rachio_hose_client import RachioHoseClient
from lib.MyPushover import Pushover
from RachioFlume.reporter import WeeklyReporter
from lib.logger import get_logger
from lib.config import get_config
from datetime import datetime, timedelta

# Load config at module level
cfg = get_config()

# Create default database path using cfg.paths.logging_dir
DB_PATH = cfg.paths.logging_dir + "/water_tracking.db"
pushover = Pushover(
    cfg.pushover.user,
    cfg.pushover.tokens.get("RachioFlume", cfg.pushover.default_token),
)


def main() -> int:
    """Main entry point with command line interface."""
    # Setup logging first
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting Rachio-Flume Water Tracking Integration")

    parser = argparse.ArgumentParser(description="Rachio-Flume Water Tracking Integration")

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

    # List-devices command
    subparsers.add_parser(
        "list-devices",
        help="List all Rachio devices visible from the API (controllers + hose timers)",
    )

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
    report_parser.add_argument("--email", action="store_true", help="Send report via email")

    # Summary command
    subparsers.add_parser("summary", help="Generate efficiency analysis")

    # Raw data command
    raw_parser = subparsers.add_parser("raw", help="Generate raw data report (5-minute intervals)")
    raw_parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of hours for raw data report (default: 24)",
    )

    # Simulate command (synthetic playback — no Pushover sent)
    sim_parser = subparsers.add_parser(
        "simulate",
        help="Replay a synthetic scenario through the alert engine (screen only, no Pushover)",
    )
    sim_parser.add_argument(
        "--config",
        type=str,
        default="config/synthetic_alerts.yaml",
        help="Path to synthetic scenario YAML (default: config/synthetic_alerts.yaml)",
    )
    sim_parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Simulated poll cadence in minutes (default: 5)",
    )

    # Alerts subcommands
    alerts_parser = subparsers.add_parser("alerts", help="Manage usage alerts")
    alerts_sub = alerts_parser.add_subparsers(dest="alerts_command", help="Alert subcommands")
    alerts_sub.add_parser("test", help="Dry-run evaluate all rules (no Pushover sent)")
    alerts_sub.add_parser("status", help="Show per-rule state")
    replay_parser = alerts_sub.add_parser(
        "replay",
        help="Replay last N hours of production DB through alert rules (no Pushover)",
    )
    replay_parser.add_argument(
        "--hours", type=int, default=24, help="Hours of history to replay (default: 24)"
    )
    replay_parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Simulated poll cadence in minutes (default: 5)",
    )
    replay_parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite DB (default: production DB from config)",
    )
    mute_parser = alerts_sub.add_parser("mute", help="Mute a rule for N hours")
    mute_parser.add_argument("rule", help="Rule name (e.g. 'Pipe Break')")
    mute_parser.add_argument("--hours", type=float, default=4.0, help="Mute duration (default 4h)")
    unmute_parser = alerts_sub.add_parser("unmute", help="Clear mute on a rule")
    unmute_parser.add_argument("rule", help="Rule name (e.g. 'Pipe Break')")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "collect":
        return run_collection(args)
    elif args.command == "status":
        return show_status(args)
    elif args.command == "list-devices":
        return list_devices(args)
    elif args.command == "report":
        return generate_report(args)
    elif args.command == "summary":
        return generate_summary_report(args)
    elif args.command == "raw":
        return generate_raw_report(args)
    elif args.command == "alerts":
        return run_alerts_command(args)
    elif args.command == "simulate":
        return run_simulate_command(args)

    return 0


def _build_alert_engine() -> AlertEngine:
    """Construct an AlertEngine sharing the rfmanager-level Pushover instance.

    Uses the first controller device in cfg.rachio.devices. Zone thresholds
    are filtered to that controller's labelled block.
    """
    rules = load_rules_from_config()
    all_thresholds = load_zone_thresholds_from_config()
    alerts_cfg = cfg.rachio_flume.alerts

    controllers = [d for d in cfg.rachio.devices if d.type == "controller"]
    if not controllers:
        raise ValueError("No controller device configured in cfg.rachio.devices")
    primary = controllers[0]
    rachio_client = RachioClient(device_id=primary.id, label=primary.label)
    controller_thresholds = get_controller_zone_thresholds(all_thresholds, primary.label)

    return AlertEngine(
        flume_client=FlumeClient(),
        rachio_client=rachio_client,
        pushover=pushover,
        db=WaterTrackingDB(DB_PATH),
        rules=rules,
        zone_thresholds=controller_thresholds,
        absolute_gpm=alerts_cfg.absolute_gpm,
        percent_above=alerts_cfg.percent_above,
        min_runtime_minutes=alerts_cfg.min_runtime_minutes,
    )


def _build_hose_processors(db: WaterTrackingDB) -> list[HoseTimerProcessor]:
    """One HoseTimerProcessor per Smart Hose Timer base station in config.

    Each processor gets a shared FlumeClient so the zone-end report uses the
    same house-water source as the controller path.
    """
    all_thresholds = load_zone_thresholds_from_config()
    flume_client = (
        FlumeClient() if any(d.type == "hose_timer" for d in cfg.rachio.devices) else None
    )
    processors: list[HoseTimerProcessor] = []
    for dev in cfg.rachio.devices:
        if dev.type != "hose_timer":
            continue
        client = RachioHoseClient(
            api_key=cfg.rachio.api_key,
            base_station_id=dev.id,
            label=dev.label,
        )
        processors.append(
            HoseTimerProcessor(
                client=client,
                pushover=pushover,
                db=db,
                thresholds=all_thresholds.get(dev.label, {}),
                flume_client=flume_client,
            )
        )
    return processors


def run_collection(args: argparse.Namespace) -> int:
    """Run data collection."""
    logger = get_logger(__name__)

    try:
        cfg = get_config()
        alert_engine = _build_alert_engine() if cfg.rachio_flume.alerts.enabled else None
        db = WaterTrackingDB(DB_PATH)
        hose_processors = _build_hose_processors(db)
        collector = WaterTrackingCollector(
            DB_PATH,
            args.interval,
            alert_engine=alert_engine,
            hose_processors=hose_processors,
        )
        if alert_engine is not None:
            logger.info(f"Alerts enabled with {len(alert_engine.rules)} rules")
        if hose_processors:
            logger.info(
                f"Hose-timer processors active for: {[p.client.label for p in hose_processors]}"
            )

        logger.info(f"Starting continuous collection every {args.interval} seconds")
        logger.info("Press Ctrl+C to stop")
        asyncio.run(collector.run_continuous())
        return 0

    except KeyboardInterrupt:
        logger.info("Collection stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Error during collection: {e}")
        pushover.send_message(
            f"Error during collection: {e}",
            title="RachioFlume Error",
            priority=2,
        )
        sleep(3600)  ## cooldown for an hour.
        return 1


def list_devices(_args: argparse.Namespace) -> int:
    """Print all Rachio devices visible from the live API."""
    import requests

    logger = get_logger(__name__)
    api_key = cfg.rachio.api_key
    if not api_key:
        logger.error("cfg.rachio.api_key is empty")
        return 1
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        person = requests.get(
            "https://api.rach.io/1/public/person/info", headers=headers, timeout=10
        ).json()
        pid = person["id"]
        info = requests.get(
            f"https://api.rach.io/1/public/person/{pid}", headers=headers, timeout=10
        ).json()
        bs = requests.get(
            f"https://cloud-rest.rach.io/valve/listBaseStations/{pid}",
            headers=headers,
            timeout=10,
        ).json()
    except Exception as e:
        logger.error(f"Rachio API error: {e}")
        return 1

    logger.info("=" * 60)
    logger.info(f"Rachio person_id: {pid}")
    logger.info("=" * 60)

    logger.info("Controllers (Smart Sprinkler):")
    for d in info.get("devices", []):
        zones = [(z.get("zoneNumber"), z.get("name")) for z in d.get("zones", [])]
        logger.info(
            f"  id={d.get('id')}  name='{d.get('name')}'  model={d.get('model')}  "
            f"on={d.get('on')}  zones={len(zones)}"
        )

    logger.info("")
    logger.info("Hose-Timer base stations (Smart Hose Timer):")
    for b in bs.get("baseStations", []):
        try:
            valves = requests.get(
                f"https://cloud-rest.rach.io/valve/listValves/{b['id']}",
                headers=headers,
                timeout=10,
            ).json()
            valve_list = [v.get("name") for v in valves.get("valves", [])]
        except Exception as e:
            valve_list = [f"<error: {e}>"]
        logger.info(
            f"  id={b.get('id')}  name='{b.get('name')}'  "
            f"serial={b.get('serialNumber')}  valves={valve_list}"
        )

    logger.info("=" * 60)
    return 0


def show_status(_args: argparse.Namespace) -> int:
    """Show current system status."""
    logger = get_logger(__name__)

    try:
        collector = WaterTrackingCollector(DB_PATH)
        status = collector.get_current_status()

        logger.info("=" * 50)
        logger.info("WATER TRACKING SYSTEM STATUS")
        logger.info("=" * 50)

        if "error" in status:
            logger.error(f"Error: {status['error']}")
            return 1

        active_zone = status["active_zone"]
        if active_zone["zone_number"]:
            logger.info(f"Active Zone: #{active_zone['zone_number']} - {active_zone['zone_name']}")
        else:
            logger.info("Active Zone: None")

        if status["current_usage_rate_gpm"]:
            logger.info(f"Current Usage Rate: {status['current_usage_rate_gpm']:.2f} GPM")
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


def generate_report(args: argparse.Namespace) -> int:
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
        pushover.send_message(
            f"Error generating report: {e}",
            title="RachioFlume Report Error",
            priority=2,
        )
        return 1


def generate_summary_report(_args: argparse.Namespace) -> int:
    """Generate efficiency analysis reports."""
    logger = get_logger(__name__)

    try:
        reporter = WeeklyReporter(DB_PATH)

        analysis = reporter.get_zone_efficiency_analysis()
        reporter.print_efficiency_analysis(analysis)

        return 0

    except Exception as e:
        logger.error(f"Error generating summary report: {e}")
        pushover.send_message(
            f"Error generating summary report: {e}",
            title="RachioFlume Report Error",
            priority=2,
        )
        return 1


def generate_raw_report(args: argparse.Namespace) -> int:
    """Generate raw data reports."""
    logger = get_logger(__name__)

    try:
        reporter = WeeklyReporter(DB_PATH)

        report = reporter.generate_raw_data_report(args.hours)
        reporter.print_raw_report(report)

        return 0

    except Exception as e:
        logger.error(f"Error generating raw report: {e}")
        pushover.send_message(
            f"Error generating raw report: {e}",
            title="RachioFlume Report Error",
            priority=2,
        )
        return 1


def run_simulate_command(args: argparse.Namespace) -> int:
    """Replay a synthetic scenario through the alert engine and print events."""
    from RachioFlume.simulate_alerts import run_simulation_from_yaml

    logger = get_logger(__name__)
    try:
        run_simulation_from_yaml(args.config, poll_interval_minutes=args.poll_interval)
        return 0
    except FileNotFoundError as e:
        logger.error(f"Scenario file not found: {e}")
        return 1
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        return 1


def run_alerts_command(args: argparse.Namespace) -> int:
    """Dispatch the `alerts` subcommands (test/status/replay/mute/unmute)."""
    logger = get_logger(__name__)

    if not args.alerts_command:
        logger.error("alerts: subcommand required (test|status|replay|mute|unmute)")
        return 1

    if args.alerts_command == "replay":
        from RachioFlume.simulate_alerts import run_replay

        run_replay(
            args.db or DB_PATH,
            args.hours,
            rules=load_rules_from_config(),
            poll_interval_minutes=args.poll_interval,
        )
        return 0

    engine = _build_alert_engine()

    if args.alerts_command == "test":
        results = asyncio.run(engine.evaluate(dry_run=True))
        for r in results:
            logger.info(r)
        return 0

    if args.alerts_command == "status":
        for row in engine.status():
            logger.info(row)
        return 0

    if args.alerts_command == "mute":
        try:
            state = engine.mute(args.rule, args.hours)
        except ValueError as e:
            logger.error(str(e))
            return 1
        logger.info(f"Muted '{args.rule}' until {state.mute_until}")
        return 0

    if args.alerts_command == "unmute":
        try:
            engine.unmute(args.rule)
        except ValueError as e:
            logger.error(str(e))
            return 1
        logger.info(f"Unmuted '{args.rule}'")
        return 0

    logger.error(f"Unknown alerts subcommand: {args.alerts_command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
