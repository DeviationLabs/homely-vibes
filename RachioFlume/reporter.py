"""Weekly reporting system for water tracking data."""

import json
from datetime import datetime, timedelta
from typing import Dict, Any
from pathlib import Path

from data_storage import WaterTrackingDB
from lib.logger import get_logger


class WeeklyReporter:
    """Generate weekly water usage reports by zone."""

    def __init__(self, db_path: str = "water_tracking.db"):
        """Initialize the reporter.

        Args:
            db_path: Path to SQLite database
        """
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

    def print_report(self, report: Dict[str, Any]) -> None:
        """Print report in a readable format."""
        print("\\n" + "=" * 60)
        print("WEEKLY WATER USAGE REPORT")
        print(f"Week: {report['week_start'][:10]} to {report['week_end'][:10]}")
        print("=" * 60)

        summary = report["summary"]
        print("\\nSUMMARY:")
        print(f"  Total watering sessions: {summary['total_watering_sessions']}")
        print(f"  Total duration: {summary['total_duration_hours']} hours")
        print(f"  Total water used: {summary['total_water_used_gallons']} gallons")
        print(f"  Zones watered: {summary['zones_watered']}")

        if report["zones"]:
            print("\\nZONE DETAILS:")
            print(
                f"{'Zone':<4} {'Name':<20} {'Sessions':<8} {'Duration(h)':<12} {'Water(gal)':<12} {'Avg Rate(gpm)':<14}"
            )
            print("-" * 70)

            for zone in report["zones"]:
                print(
                    f"{zone['zone_number']:<4} {zone['zone_name']:<20} "
                    f"{zone['sessions']:<8} {zone['total_duration_hours']:<12} "
                    f"{zone['total_water_gallons']:<12} {zone['average_flow_rate_gpm']:<14}"
                )

        print("\\n" + "=" * 60 + "\\n")

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


def main():
    """Main entry point for generating reports."""
    import sys

    reporter = WeeklyReporter()

    if "--current-week" in sys.argv:
        report = reporter.generate_current_week_report()
        reporter.print_report(report)

        if "--save" in sys.argv:
            filename = f"weekly_report_{report['week_start'][:10]}.json"
            reporter.save_report_to_file(report, filename)
            print(f"Report saved to {filename}")

    elif "--last-week" in sys.argv:
        report = reporter.generate_last_week_report()
        reporter.print_report(report)

        if "--save" in sys.argv:
            filename = f"weekly_report_{report['week_start'][:10]}.json"
            reporter.save_report_to_file(report, filename)
            print(f"Report saved to {filename}")

    elif "--efficiency" in sys.argv:
        analysis = reporter.get_zone_efficiency_analysis()
        print("\\n" + "=" * 60)
        print("ZONE EFFICIENCY ANALYSIS")
        print(f"Period: {analysis['analysis_period']}")
        print("=" * 60)

        for zone_name, data in analysis["zones"].items():
            print(f"\\n{zone_name}:")
            print(f"  Sessions: {data['total_sessions']}")
            print(f"  Avg flow rate: {data['average_flow_rate_gpm']} GPM")
            print(f"  Water per session: {data['water_per_session_gallons']} gallons")
            print(
                f"  Duration per session: {data['duration_per_session_minutes']} minutes"
            )

    else:
        print("Usage:")
        print("  python reporter.py --current-week [--save]")
        print("  python reporter.py --last-week [--save]")
        print("  python reporter.py --efficiency")


if __name__ == "__main__":
    main()
