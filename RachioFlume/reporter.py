"""Weekly reporting system for water tracking data."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

from RachioFlume.alert_rules import compact_zone_label, load_zone_thresholds_from_config
from RachioFlume.data_storage import WaterTrackingDB
from lib.config import get_config
from lib.logger import get_logger
from lib import Mailer


@dataclass
class ZoneStats:
    """Statistics for a single zone (controller zone or hose-timer valve)."""

    zone_number: int  # controller zone number; hose valves use HOSE_ZONE_SENTINEL
    zone_name: str
    sessions: int
    total_duration_minutes: float
    average_duration_minutes: float
    total_water_gallons: float
    average_flow_rate_gpm: float
    threshold_gpm: float
    alert_sessions: int


# Hose valves have no controller zone number; sort them after real zones.
HOSE_ZONE_SENTINEL = 999


@dataclass
class ReportSummary:
    """Summary statistics for the entire report."""

    total_watering_sessions: int
    total_duration_minutes: float
    total_water_used_gallons: float
    zones_watered: int


@dataclass
class WaterUsageReport:
    """Complete water usage report."""

    report_generated: datetime
    period_start: datetime
    period_end: datetime
    summary: ReportSummary
    zones: List[ZoneStats]

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
        # Assumes a single controller per deployment (current setup: Rachio-Eden).
        # If two controllers ever share a zone number, the later-processed entry
        # would overwrite. Revisit when multi-controller support lands.
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

        # Aggregate hose-timer sessions and append as rows in the same table.
        # Hose valves are treated identically to controller zones: they count
        # toward zones_watered, contribute to total sessions / total duration,
        # and share the same column layout. Volume + rate come from the Flume
        # window aggregate captured by hose_timer_processor at run end.
        hose_sessions = self.db.get_hose_zone_sessions(period_start, period_end)
        hose_agg: Dict[tuple, Dict[str, Any]] = {}
        hose_alerts: Dict[tuple, int] = {}
        for s in hose_sessions:
            key = (s["base_station_label"], s["valve_name"])
            slot = hose_agg.setdefault(
                key, {"sessions": 0, "duration_sec_total": 0, "gal_total": 0.0}
            )
            slot["sessions"] += 1
            duration_sec = s.get("duration_seconds") or 0
            slot["duration_sec_total"] += duration_sec
            gal = float(s.get("total_water_used") or 0.0)
            slot["gal_total"] += gal
            hose_zt = all_thresholds.get(s["base_station_label"], {}).get(s["valve_name"])
            if hose_zt and duration_sec > 0:
                sess_avg = gal / (duration_sec / 60.0)
                if sess_avg > hose_zt.compute_threshold(abs_gpm, pct_above):
                    hose_alerts[key] = hose_alerts.get(key, 0) + 1

        for (label, name), v in hose_agg.items():
            zt = all_thresholds.get(label, {}).get(name)
            threshold_gpm = round(zt.compute_threshold(abs_gpm, pct_above), 2) if zt else 0.0
            dur_min = v["duration_sec_total"] / 60.0
            avg_gpm = v["gal_total"] / dur_min if dur_min > 0 else 0.0
            formatted_zones.append(
                ZoneStats(
                    zone_number=HOSE_ZONE_SENTINEL,
                    zone_name=compact_zone_label(name),
                    sessions=v["sessions"],
                    total_duration_minutes=round(dur_min, 1),
                    average_duration_minutes=round(
                        (v["duration_sec_total"] / max(v["sessions"], 1)) / 60.0, 1
                    ),
                    total_water_gallons=round(v["gal_total"], 1),
                    average_flow_rate_gpm=round(avg_gpm, 1),
                    threshold_gpm=threshold_gpm,
                    alert_sessions=hose_alerts.get((label, name), 0),
                )
            )

        # Sort: controller zones by number, hose valves alphabetical after them
        formatted_zones.sort(key=lambda x: (x.zone_number, x.zone_name))

        # Summary aggregates over the merged list so zones_watered / totals
        # include hose valves.
        summary = ReportSummary(
            total_watering_sessions=sum(z.sessions for z in formatted_zones),
            total_duration_minutes=round(sum(z.total_duration_minutes for z in formatted_zones), 1),
            total_water_used_gallons=round(sum(z.total_water_gallons for z in formatted_zones), 1),
            zones_watered=len(formatted_zones),
        )

        return WaterUsageReport(
            report_generated=datetime.now(),
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            zones=formatted_zones,
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
        """Generate the fixed-width plaintext body of the report.

        Wrapped in `<html><body><pre>...</pre></body></html>` by
        `format_report_html` for email delivery — Mailer auto-detects the
        `<html>` prefix and sends HTML. Kept as a separate step so
        `print_report` and tests can inspect the raw text.
        """
        lines: List[str] = []

        lines.append("WATER USAGE REPORT")
        lines.append(f"Period: {report.period_start.date()} to {report.period_end.date()}")
        lines.append("=" * 40)

        lines.append("")
        lines.append("SUMMARY:")
        lines.append(f"  Total duration: {report.summary.total_duration_minutes} min")
        lines.append(
            f"  Total water used: {int(round(report.summary.total_water_used_gallons))} gallons"
        )
        lines.append(f"  Zones watered: {report.summary.zones_watered}")

        if report.zones:
            lines.append("")
            lines.append("ZONE DETAILS:")
            # Numeric columns are right-aligned so decimals and thousands align
            # visually down the column. Name stays left-aligned.
            # Thr = anomaly threshold GPM (blank if zone not configured).
            # Alrt = # sessions in period where session avg flow > threshold.
            header = f"{'Name':<8} {'Min':>6} {'Gals':>5} {'GPM':>5} {'Thr':>5} {'Alrt':>4}"
            lines.append(header)
            lines.append("-" * len(header))

            for zone in report.zones:
                thr = f"{zone.threshold_gpm:.1f}" if zone.threshold_gpm > 0 else "-"
                alrt = str(zone.alert_sessions) if zone.alert_sessions else "-"
                lines.append(
                    f"{zone.zone_name[:8]:<8} "
                    f"{zone.total_duration_minutes:>6.1f} "
                    f"{int(round(zone.total_water_gallons)):>5d} "
                    f"{zone.average_flow_rate_gpm:>5.1f} "
                    f"{thr:>5} "
                    f"{alrt:>4}"
                )

        lines.append("")
        lines.append("=" * 40)
        return "\n".join(lines)

    def format_report_html(self, report: WaterUsageReport) -> str:
        """HTML wrapper so iOS Mail / Gmail render fixed-width without wrap."""
        body = self.format_report_text(report)
        return (
            "<html><body>"
            "<pre style=\"font-family: 'SF Mono', Menlo, Consolas, monospace; "
            'font-size: 13px; line-height: 1.3;">'
            f"{body}"
            "</pre></body></html>"
        )

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
        # HTML wrapper — Mailer auto-detects the `<html>` prefix and sends
        # multipart/HTML. Renders fixed-width in iOS Mail / Gmail without wrap.
        report_html = self.format_report_html(report)

        start_date = report.period_start.date()
        subject_prefix = "Period"

        Mailer.sendmail(
            topic=f"[Water Report] {subject_prefix} {start_date}",
            alert=alert,
            message=report_html,
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
