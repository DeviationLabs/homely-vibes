"""Weekly reporting system for water tracking data."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

from data_storage import WaterTrackingDB
from lib.logger import get_logger
from lib import Mailer


@dataclass
class ZoneStats:
    """Statistics for a single zone."""

    zone_number: int
    zone_name: str
    sessions: int
    total_duration_hours: float
    average_duration_minutes: float
    total_water_gallons: float
    average_flow_rate_gpm: float


@dataclass
class ReportSummary:
    """Summary statistics for the entire report."""

    total_watering_sessions: int
    total_duration_hours: float
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

        # Get zone statistics for the period
        zone_stats = self.db.get_period_zone_stats(period_start, period_end)

        # Calculate total statistics
        total_sessions = sum(stat["session_count"] for stat in zone_stats)
        total_duration_seconds = sum(stat["total_duration_seconds"] or 0 for stat in zone_stats)
        total_water_used = sum(stat["total_water_used"] or 0 for stat in zone_stats)

        # Format zone statistics for display
        formatted_zones = []
        for stat in zone_stats:
            duration_hours = (stat["total_duration_seconds"] or 0) / 3600
            avg_duration_minutes = (stat["avg_duration_seconds"] or 0) / 60

            zone_stats_obj = ZoneStats(
                zone_number=stat["zone_number"],
                zone_name=stat["zone_name"],
                sessions=stat["session_count"],
                total_duration_hours=round(duration_hours, 2),
                average_duration_minutes=round(avg_duration_minutes, 1),
                total_water_gallons=round(stat["total_water_used"] or 0, 1),
                average_flow_rate_gpm=round(stat["avg_flow_rate"] or 0, 2),
            )
            formatted_zones.append(zone_stats_obj)

        # Sort by zone number
        formatted_zones.sort(key=lambda x: x.zone_number)

        # Create summary
        summary = ReportSummary(
            total_watering_sessions=total_sessions,
            total_duration_hours=round(total_duration_seconds / 3600, 2),
            total_water_used_gallons=round(total_water_used, 1),
            zones_watered=len(zone_stats),
        )

        # Create and return the report
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
        report_text.append(f"  Total duration: {report.summary.total_duration_hours} hours")
        report_text.append(f"  Total water used: {report.summary.total_water_used_gallons} gallons")
        report_text.append(f"  Zones watered: {report.summary.zones_watered}")

        if report.zones:
            report_text.append("\nZONE DETAILS:")
            # Use fixed-width formatting for better display
            header = f"{'Name':<8} {'Runs':<4} {'Hrs':<5} {'Gals':<5} {'GPM':<4}"
            report_text.append(header)
            report_text.append("-" * len(header))

            for zone in report.zones:
                zone_line = (
                    f"{zone.zone_name[:8]:<8} "
                    f"{zone.sessions:<4} "
                    f"{zone.total_duration_hours:<5.1f} "
                    f"{zone.total_water_gallons:<5.1f} "
                    f"{zone.average_flow_rate_gpm:<4.1f}"
                )
                report_text.append(zone_line)

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

    def get_zone_efficiency_analysis(self, weeks_back: int = 4) -> Dict[str, Any]:
        """Analyze zone efficiency over multiple weeks.

        Args:
            weeks_back: Number of weeks to analyze

        Returns:
            Efficiency analysis by zone
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(weeks=weeks_back)

        # Get all sessions in the period
        sessions = self.db.get_zone_sessions(start_date, end_date)

        # Group by zone
        zone_data: Dict[str, Dict[str, Any]] = {}
        for session in sessions:
            zone_name = session["zone_name"]
            if zone_name not in zone_data:
                zone_data[zone_name] = {
                    "sessions": [],
                    "total_water": 0,
                    "total_duration": 0,
                }

            zone_data[zone_name]["sessions"].append(session)
            zone_data[zone_name]["total_water"] += session.get("total_water_used", 0)
            zone_data[zone_name]["total_duration"] += session.get("duration_seconds", 0)

        # Calculate efficiency metrics
        efficiency_analysis: Dict[str, Dict[str, Any]] = {}
        for zone_name, data in zone_data.items():
            if data["total_duration"] > 0:
                avg_flow_rate = data["total_water"] / (data["total_duration"] / 60)  # GPM
                water_per_session = data["total_water"] / len(data["sessions"])
                duration_per_session = (
                    data["total_duration"] / len(data["sessions"]) / 60
                )  # minutes

                efficiency_analysis[zone_name] = {
                    "total_sessions": len(data["sessions"]),
                    "average_flow_rate_gpm": round(avg_flow_rate, 2),
                    "water_per_session_gallons": round(water_per_session, 1),
                    "duration_per_session_minutes": round(duration_per_session, 1),
                    "total_water_gallons": round(data["total_water"], 1),
                    "total_duration_hours": round(data["total_duration"] / 3600, 2),
                }

        return {
            "analysis_period": f"{start_date.date()} to {end_date.date()}",
            "weeks_analyzed": weeks_back,
            "zones": efficiency_analysis,
        }

    def format_efficiency_text(self, analysis: Dict[str, Any]) -> str:
        """Generate formatted text version of efficiency analysis.

        Args:
            analysis: Efficiency analysis data

        Returns:
            Formatted analysis as string
        """
        report_text = []
        report_text.append("ZONE EFFICIENCY ANALYSIS")
        report_text.append(f"Period: {analysis['analysis_period']}")
        report_text.append("=" * 60)

        if not analysis["zones"]:
            report_text.append("No zone data available for analysis.")
            return "\n".join(report_text)

        for zone_name, data in analysis["zones"].items():
            report_text.append(f"\n{zone_name}:")
            report_text.append(f"  Sessions: {data['total_sessions']}")
            report_text.append(f"  Avg flow rate: {data['average_flow_rate_gpm']} GPM")
            report_text.append(f"  Water per session: {data['water_per_session_gallons']} gallons")
            report_text.append(
                f"  Duration per session: {data['duration_per_session_minutes']} minutes"
            )

        report_text.append("\n" + "=" * 60)
        return "\n".join(report_text)

    def print_efficiency_analysis(self, analysis: Dict[str, Any]) -> None:
        """Print efficiency analysis in a readable format."""
        analysis_text = self.format_efficiency_text(analysis)

        # Log each line separately for proper logger formatting
        for line in analysis_text.split("\n"):
            self.logger.info(line)


def main() -> None:
    """Main entry point for generating reports."""
    import sys

    reporter = WeeklyReporter("water_tracking.db")

    if "--efficiency" in sys.argv:
        analysis = reporter.get_zone_efficiency_analysis()
        reporter.print_efficiency_analysis(analysis)
    else:
        print("Usage:")
        print("  python reporter.py --efficiency")
        print("")
        print("Options:")
        print("  --efficiency  Generate zone efficiency analysis")


if __name__ == "__main__":
    main()
