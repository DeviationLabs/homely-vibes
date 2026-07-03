"""Weekly reporting system for water tracking data."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

from RachioFlume.alert_rules import load_zone_thresholds_from_config
from RachioFlume.data_storage import WaterTrackingDB
from lib.config import get_config
from lib.logger import get_logger
from lib import Mailer


@dataclass
class ZoneStats:
    """Statistics for a single zone."""

    zone_number: int
    zone_name: str
    sessions: int
    total_duration_minutes: float
    average_duration_minutes: float
    total_water_gallons: float
    average_flow_rate_gpm: float
    threshold_gpm: float
    alert_sessions: int


@dataclass
class ReportSummary:
    """Summary statistics for the entire report."""

    total_watering_sessions: int
    total_duration_minutes: float
    total_water_used_gallons: float
    zones_watered: int


@dataclass
class HoseValveStats:
    """Statistics for a single hose-timer valve in a reporting period."""

    base_station_label: str
    valve_name: str
    sessions: int
    total_duration_minutes: float
    average_duration_minutes: float
    flow_detected_sessions: int
    threshold_gpm: float
    alert_sessions: int


@dataclass
class WaterUsageReport:
    """Complete water usage report."""

    report_generated: datetime
    period_start: datetime
    period_end: datetime
    summary: ReportSummary
    zones: List[ZoneStats]
    hose_valves: List[HoseValveStats] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for compatibility."""
        return asdict(self)


class WeeklyReporter:
    """Generate weekly water usage reports by zone."""

    def __init__(self, db_path: str):
        self.db = WaterTrackingDB(db_path)
        self.logger = get_logger(__name__)
        self.logger.info("Weekly reporter initialized")

    def generate_period_report_with_dates(
        self, period_start: datetime, period_end: datetime
    ) -> WaterUsageReport:
        """Generate a comprehensive period report.

        Args:
            period_start: Start of the period
            period_end: End of the period

        Returns:
            WaterUsageReport containing period statistics
        """
        self.logger.info(
            f"Generating period report for {period_start.date()} to {period_end.date()}"
        )

        # Load anomaly config once — used to compute per-zone / per-valve
        # threshold (baseline + slack) and count how many sessions crossed it.
        cfg = get_config()
        za_cfg = cfg.rachio_flume.alerts.zone_anomaly
        abs_gpm = za_cfg.absolute_gpm
        pct_above = za_cfg.percent_above

        try:
            all_thresholds = load_zone_thresholds_from_config()
        except Exception:
            all_thresholds = {}

        # Controller thresholds: flatten by str(zone_number). Hose keys (non-digit)
        # skipped; they're merged into the hose section below.
        ctrl_thresh: Dict[str, Any] = {}
        for _label, zones in all_thresholds.items():
            for zone_key, zone_zt in zones.items():
                if zone_key.isdigit():
                    ctrl_thresh[zone_key] = zone_zt

        # Per-session alert counts by zone_number and by (label, valve_name).
        ctrl_alerts: Dict[int, int] = {}
        for s in self.db.get_zone_sessions(period_start, period_end):
            sess_zt = ctrl_thresh.get(str(s["zone_number"]))
            if sess_zt and (s.get("avg_flow_rate") or 0) > sess_zt.compute_threshold(
                abs_gpm, pct_above
            ):
                ctrl_alerts[s["zone_number"]] = ctrl_alerts.get(s["zone_number"], 0) + 1

        # Get zone aggregate statistics for the period
        zone_stats = self.db.get_period_zone_stats(period_start, period_end)

        # Calculate total statistics
        total_sessions = sum(stat["session_count"] for stat in zone_stats)
        total_duration_seconds = sum(stat["total_duration_seconds"] or 0 for stat in zone_stats)
        total_water_used = sum(stat["total_water_used"] or 0 for stat in zone_stats)

        # Format zone statistics for display
        formatted_zones = []
        for stat in zone_stats:
            duration_minutes = (stat["total_duration_seconds"] or 0) / 60.0
            avg_duration_minutes = (stat["avg_duration_seconds"] or 0) / 60.0
            stat_zt = ctrl_thresh.get(str(stat["zone_number"]))
            threshold_gpm = (
                round(stat_zt.compute_threshold(abs_gpm, pct_above), 2) if stat_zt else 0.0
            )

            zone_stats_obj = ZoneStats(
                zone_number=stat["zone_number"],
                zone_name=stat["zone_name"],
                sessions=stat["session_count"],
                total_duration_minutes=round(duration_minutes, 1),
                average_duration_minutes=round(avg_duration_minutes, 1),
                total_water_gallons=round(stat["total_water_used"] or 0, 1),
                average_flow_rate_gpm=round(stat["avg_flow_rate"] or 0, 2),
                threshold_gpm=threshold_gpm,
                alert_sessions=ctrl_alerts.get(stat["zone_number"], 0),
            )
            formatted_zones.append(zone_stats_obj)

        # Sort by zone number
        formatted_zones.sort(key=lambda x: x.zone_number)

        # Create summary
        summary = ReportSummary(
            total_watering_sessions=total_sessions,
            total_duration_minutes=round(total_duration_seconds / 60.0, 1),
            total_water_used_gallons=round(total_water_used, 1),
            zones_watered=len(zone_stats),
        )

        # Aggregate hose-timer sessions
        hose_sessions = self.db.get_hose_zone_sessions(period_start, period_end)
        hose_agg: Dict[tuple, Dict[str, Any]] = {}
        hose_alerts: Dict[tuple, int] = {}
        for s in hose_sessions:
            key = (s["base_station_label"], s["valve_name"])
            slot = hose_agg.setdefault(
                key,
                {"sessions": 0, "duration_sec_total": 0, "flow_detected": 0},
            )
            slot["sessions"] += 1
            duration_sec = s.get("duration_seconds") or 0
            slot["duration_sec_total"] += duration_sec
            if s.get("flow_detected"):
                slot["flow_detected"] += 1
            # Hose anomaly: session avg flow (gallons / minutes) vs. threshold
            hose_zt = all_thresholds.get(s["base_station_label"], {}).get(s["valve_name"])
            gal = s.get("total_water_used") or 0
            if hose_zt and duration_sec > 0:
                sess_avg = gal / (duration_sec / 60.0)
                if sess_avg > hose_zt.compute_threshold(abs_gpm, pct_above):
                    hose_alerts[key] = hose_alerts.get(key, 0) + 1

        def _hose_display_and_threshold(label: str, raw_name: str) -> tuple[str, float]:
            zt = all_thresholds.get(label, {}).get(raw_name)
            if not zt:
                return raw_name, 0.0
            return zt.name, round(zt.compute_threshold(abs_gpm, pct_above), 2)

        hose_valves_unsorted = []
        for (label, name), v in hose_agg.items():
            display_name, threshold_gpm = _hose_display_and_threshold(label, name)
            hose_valves_unsorted.append(
                HoseValveStats(
                    base_station_label=label,
                    valve_name=display_name,
                    sessions=v["sessions"],
                    total_duration_minutes=round(v["duration_sec_total"] / 60.0, 1),
                    average_duration_minutes=round(
                        (v["duration_sec_total"] / max(v["sessions"], 1)) / 60.0, 1
                    ),
                    flow_detected_sessions=v["flow_detected"],
                    threshold_gpm=threshold_gpm,
                    alert_sessions=hose_alerts.get((label, name), 0),
                )
            )
        hose_valves = sorted(
            hose_valves_unsorted, key=lambda h: (h.base_station_label, h.valve_name)
        )

        # Create and return the report
        return WaterUsageReport(
            report_generated=datetime.now(),
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            zones=formatted_zones,
            hose_valves=hose_valves,
        )

    def save_report_to_file(self, report: WaterUsageReport, filename: str) -> None:
        """Save report to JSON file.

        Args:
            report: Report data
            filename: Output filename
        """
        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)

    def format_report_text(self, report: WaterUsageReport) -> str:
        """Generate formatted text version of the report.

        Args:
            report: Report data

        Returns:
            Formatted report as string
        """
        report_text = []

        report_text.append("WATER USAGE REPORT")
        report_text.append(f"Period: {report.period_start.date()} to {report.period_end.date()}")
        report_text.append("=" * 35)

        report_text.append("\nSUMMARY:")
        report_text.append(f"  Total watering sessions: {report.summary.total_watering_sessions}")
        report_text.append(f"  Total duration: {report.summary.total_duration_minutes} min")
        report_text.append(f"  Total water used: {report.summary.total_water_used_gallons} gallons")
        report_text.append(f"  Zones watered: {report.summary.zones_watered}")

        if report.zones:
            report_text.append("\nZONE DETAILS:")
            # Thr = anomaly threshold GPM (blank if zone not configured).
            # Alrt = # sessions in period where session avg flow > threshold.
            header = (
                f"{'Name':<8} {'Runs':<4} {'Min':<6} {'Gals':<6} {'GPM':<5} {'Thr':<5} {'Alrt':<4}"
            )
            report_text.append(header)
            report_text.append("-" * len(header))

            for zone in report.zones:
                thr = f"{zone.threshold_gpm:.1f}" if zone.threshold_gpm > 0 else "-"
                alrt = str(zone.alert_sessions) if zone.alert_sessions else "-"
                zone_line = (
                    f"{zone.zone_name[:8]:<8} "
                    f"{zone.sessions:<4} "
                    f"{zone.total_duration_minutes:<6.1f} "
                    f"{zone.total_water_gallons:<6.1f} "
                    f"{zone.average_flow_rate_gpm:<5.2f} "
                    f"{thr:<5} "
                    f"{alrt:<4}"
                )
                report_text.append(zone_line)

        if report.hose_valves:
            report_text.append("\nHOSE TIMER VALVES:")
            header = (
                f"{'Base/Valve':<32} {'Runs':<4} {'Min':<6} {'Avg(m)':<6} "
                f"{'Flow':<4} {'Thr':<5} {'Alrt':<4}"
            )
            report_text.append(header)
            report_text.append("-" * len(header))
            for hv in report.hose_valves:
                label = f"{hv.base_station_label}/{hv.valve_name}"[:32]
                thr = f"{hv.threshold_gpm:.1f}" if hv.threshold_gpm > 0 else "-"
                alrt = str(hv.alert_sessions) if hv.alert_sessions else "-"
                report_text.append(
                    f"{label:<32} "
                    f"{hv.sessions:<4} "
                    f"{hv.total_duration_minutes:<6.1f} "
                    f"{hv.average_duration_minutes:<6.1f} "
                    f"{hv.flow_detected_sessions:<4} "
                    f"{thr:<5} "
                    f"{alrt:<4}"
                )

        report_text.append("\n" + "=" * 35)
        return "\n".join(report_text)

    def print_report(self, report: WaterUsageReport) -> None:
        """Print report in a readable format."""
        report_text = self.format_report_text(report)

        # Log each line separately for proper logger formatting
        for line in report_text.split("\n"):
            self.logger.info(line)

    def print_raw_report(self, report: Dict[str, Any]) -> None:
        """Print raw data report in a readable format."""
        self.logger.info("=" * 35)
        self.logger.info("RAW WATER USAGE DATA REPORT")
        self.logger.info("=" * 35)
        self.logger.info(f"Report Generated: {report['report_generated']}")
        self.logger.info(f"Time Period: {report['period_start']} to {report['period_end']}")
        self.logger.info(f"Interval: {report['interval_minutes']} minutes")
        self.logger.info(f"Total Data Points: {len(report['data_points'])}")
        self.logger.info("")

        if not report["data_points"]:
            self.logger.info("No data available for this time period.")
        else:
            self.logger.info(
                "Time Interval               | Avg GPM | Max GPM | Min GPM | Points | Active Avg"
            )
            self.logger.info("-" * 35)

            for data_point in report["data_points"]:
                time_str = data_point["interval_start"]
                avg_flow = data_point["avg_flow_rate"] or 0
                max_flow = data_point["max_flow_rate"] or 0
                min_flow = data_point["min_flow_rate"] or 0
                points = data_point["data_points"]
                active_avg = data_point["avg_active_flow_rate"] or 0

                self.logger.info(
                    f"{time_str[:16]:25} | {avg_flow:7.2f} | {max_flow:7.2f} | {min_flow:7.2f} | {points:6} | {active_avg:7.2f}"
                )

        self.logger.info("=" * 35)

    def email_report(self, report: WaterUsageReport, alert: bool = False) -> None:
        """Email report in formatted text.

        Args:
            report: Report data
            alert: Whether to mark as alert email
        """
        report_text = self.format_report_text(report)

        start_date = report.period_start.date()
        subject_prefix = "Period"

        Mailer.sendmail(
            topic=f"[Water Report] {subject_prefix} {start_date}",
            alert=alert,
            message=report_text,
            always_email=True,
        )

        self.logger.info(f"Report emailed for {subject_prefix.lower()} starting {start_date}")

    def generate_raw_data_report(self, hours_back: int = 24) -> Dict[str, Any]:
        """Generate raw data report with 5-minute increments.

        Args:
            hours_back: Number of hours to look back from now (default: 24)

        Returns:
            Dict containing raw data in 5-minute intervals
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)

        self.logger.info(f"Generating raw data report for {start_time} to {end_time}")

        # Get raw data in 5-minute intervals
        raw_data = self.db.get_raw_data_intervals(start_time, end_time, interval_minutes=5)

        return {
            "report_generated": datetime.now().isoformat(),
            "period_start": start_time.isoformat(),
            "period_end": end_time.isoformat(),
            "interval_minutes": 5,
            "data_points": raw_data,
        }
