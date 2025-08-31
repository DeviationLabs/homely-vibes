"""Weekly reporting system for water tracking data."""

import json
from datetime import datetime, timedelta
from typing import Dict, Any
from pathlib import Path

from data_storage import WaterTrackingDB
from lib.logger import get_logger
from lib import Mailer


class WeeklyReporter:
    """Generate weekly water usage reports by zone."""

    def __init__(self, db_path: str):
        self.db = WaterTrackingDB(db_path)
        self.logger = get_logger(__name__)
        self.logger.info("Weekly reporter initialized")

    def generate_weekly_report(self, week_start: datetime) -> Dict[str, Any]:
        """Generate a comprehensive weekly report.

        Args:
            week_start: Start of the week (should be Monday)

        Returns:
            Dict containing weekly statistics
        """
        week_end = week_start + timedelta(days=7)
        self.logger.info(
            f"Generating weekly report for {week_start.date()} to {week_end.date()}"
        )

        # Get zone statistics
        zone_stats = self.db.get_weekly_zone_stats(week_start)

        # Calculate total statistics
        total_sessions = sum(stat["session_count"] for stat in zone_stats)
        total_duration_seconds = sum(
            stat["total_duration_seconds"] or 0 for stat in zone_stats
        )
        total_water_used = sum(stat["total_water_used"] or 0 for stat in zone_stats)

        # Format zone statistics for display
        formatted_zones = []
        for stat in zone_stats:
            duration_hours = (stat["total_duration_seconds"] or 0) / 3600
            avg_duration_minutes = (stat["avg_duration_seconds"] or 0) / 60

            formatted_zones.append(
                {
                    "zone_number": stat["zone_number"],
                    "zone_name": stat["zone_name"],
                    "sessions": stat["session_count"],
                    "total_duration_hours": round(duration_hours, 2),
                    "average_duration_minutes": round(avg_duration_minutes, 1),
                    "total_water_gallons": round(stat["total_water_used"] or 0, 1),
                    "average_flow_rate_gpm": round(stat["avg_flow_rate"] or 0, 2),
                }
            )

        # Sort by zone number
        formatted_zones.sort(key=lambda x: x["zone_number"])

        return {
            "report_generated": datetime.now().isoformat(),
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "summary": {
                "total_watering_sessions": total_sessions,
                "total_duration_hours": round(total_duration_seconds / 3600, 2),
                "total_water_used_gallons": round(total_water_used, 1),
                "zones_watered": len(zone_stats),
            },
            "zones": formatted_zones,
        }

    def generate_current_week_report(self) -> Dict[str, Any]:
        """Generate report for the current week (Monday to Sunday)."""
        today = datetime.now().date()

        # Find the Monday of current week
        days_since_monday = today.weekday()
        monday = today - timedelta(days=days_since_monday)
        week_start = datetime.combine(monday, datetime.min.time())

        return self.generate_weekly_report(week_start)

    def generate_last_week_report(self) -> Dict[str, Any]:
        """Generate report for last week."""
        current_week_report = self.generate_current_week_report()
        last_week_start = datetime.fromisoformat(
            current_week_report["week_start"]
        ) - timedelta(days=7)

        return self.generate_weekly_report(last_week_start)

    def save_report_to_file(self, report: Dict[str, Any], filename: str) -> None:
        """Save report to JSON file.

        Args:
            report: Report data
            filename: Output filename
        """
        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

    def format_report_text(self, report: Dict[str, Any]) -> str:
        """Generate formatted text version of the report.

        Args:
            report: Report data

        Returns:
            Formatted report as string
        """
        report_text = []
        report_text.append("WEEKLY WATER USAGE REPORT")
        report_text.append(f"Week: {report['week_start'][:10]} to {report['week_end'][:10]}")
        report_text.append("=" * 70)

        summary = report["summary"]
        report_text.append("\nSUMMARY:")
        report_text.append(f"  Total watering sessions: {summary['total_watering_sessions']}")
        report_text.append(f"  Total duration: {summary['total_duration_hours']} hours")
        report_text.append(f"  Total water used: {summary['total_water_used_gallons']} gallons")
        report_text.append(f"  Zones watered: {summary['zones_watered']}")

        if report["zones"]:
            report_text.append("\nZONE DETAILS:")
            # Use fixed-width formatting for better display
            header = f"{'Zone':<6}{'Name':<22}{'Sessions':<10}{'Duration(h)':<12}{'Water(gal)':<12}{'Rate(gpm)':<10}"
            report_text.append(header)
            report_text.append("-" * len(header))

            for zone in report["zones"]:
                zone_line = (
                    f"{zone['zone_number']:<6}"
                    f"{zone['zone_name'][:20]:<22}"
                    f"{zone['sessions']:<10}"
                    f"{zone['total_duration_hours']:<12.1f}"
                    f"{zone['total_water_gallons']:<12.1f}"
                    f"{zone['average_flow_rate_gpm']:<10.1f}"
                )
                report_text.append(zone_line)

        report_text.append("\n" + "=" * 70)
        return "\n".join(report_text)

    def print_report(self, report: Dict[str, Any]) -> None:
        """Print report in a readable format."""
        report_text = self.format_report_text(report)
        
        # Log each line separately for proper logger formatting
        for line in report_text.split('\n'):
            self.logger.info(line)

    def email_report(self, report: Dict[str, Any], alert: bool = False) -> None:
        """Email report in formatted text.

        Args:
            report: Report data
            alert: Whether to mark as alert email
        """
        report_text = self.format_report_text(report)
        week_start = report['week_start'][:10]
        
        Mailer.sendmail(
            topic=f"[Water Report] Week {week_start}",
            alert=alert,
            message=report_text,
            always_email=True
        )
        
        self.logger.info(f"Weekly report emailed for week starting {week_start}")

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
        zone_data = {}
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
        efficiency_analysis = {}
        for zone_name, data in zone_data.items():
            if data["total_duration"] > 0:
                avg_flow_rate = data["total_water"] / (
                    data["total_duration"] / 60
                )  # GPM
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
            report_text.append(f"  Duration per session: {data['duration_per_session_minutes']} minutes")

        report_text.append("\n" + "=" * 60)
        return "\n".join(report_text)

    def print_efficiency_analysis(self, analysis: Dict[str, Any]) -> None:
        """Print efficiency analysis in a readable format."""
        analysis_text = self.format_efficiency_text(analysis)
        
        # Log each line separately for proper logger formatting
        for line in analysis_text.split('\n'):
            self.logger.info(line)


def main():
    """Main entry point for generating reports."""
    import sys

    reporter = WeeklyReporter("water_tracking.db")

    if "--current-week" in sys.argv:
        report = reporter.generate_current_week_report()
        reporter.print_report(report)

        if "--save" in sys.argv:
            filename = f"weekly_report_{report['week_start'][:10]}.json"
            reporter.save_report_to_file(report, filename)
            reporter.logger.info(f"Report saved to {filename}")
        
        if "--email" in sys.argv:
            alert = "--alert" in sys.argv
            reporter.email_report(report, alert=alert)
            reporter.logger.info("Report emailed")

    elif "--last-week" in sys.argv:
        report = reporter.generate_last_week_report()
        reporter.print_report(report)

        if "--save" in sys.argv:
            filename = f"weekly_report_{report['week_start'][:10]}.json"
            reporter.save_report_to_file(report, filename)
            reporter.logger.info(f"Report saved to {filename}")
        
        if "--email" in sys.argv:
            alert = "--alert" in sys.argv
            reporter.email_report(report, alert=alert)
            reporter.logger.info("Report emailed")

    elif "--efficiency" in sys.argv:
        analysis = reporter.get_zone_efficiency_analysis()
        reporter.print_efficiency_analysis(analysis)

    else:
        print("Usage:")
        print("  python reporter.py --current-week [--save] [--email] [--alert]")
        print("  python reporter.py --last-week [--save] [--email] [--alert]")
        print("  python reporter.py --efficiency")
        print("")
        print("Options:")
        print("  --save    Save report as JSON file")
        print("  --email   Send report via email")
        print("  --alert   Mark email as alert (adds [ALERT] flag)")


if __name__ == "__main__":
    main()
