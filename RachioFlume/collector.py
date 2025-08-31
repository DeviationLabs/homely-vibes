"""Data collection service that polls Rachio and Flume APIs."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from rachio_client import RachioClient
from flume_client import FlumeClient
from data_storage import WaterTrackingDB
from lib.logger import get_logger


class WaterTrackingCollector:
    """Service that collects data from Rachio and Flume APIs."""

    def __init__(
        self, db_path: str, poll_interval_seconds: int = 300
    ):  # 5 minutes default
        self.logger = get_logger(__name__)

        self.db = WaterTrackingDB(db_path)
        self.rachio_client = RachioClient()
        self.flume_client = FlumeClient()
        self.poll_interval = poll_interval_seconds

        # Track last collection times to avoid duplicates
        self.last_rachio_collection: Optional[datetime] = None
        self.last_flume_collection: Optional[datetime] = None

    async def collect_rachio_data(self) -> None:
        """Collect data from Rachio API."""
        try:
            # Collect zone information
            zones = self.rachio_client.get_zones()
            self.db.save_zones(zones)
            self.logger.info(f"Collected {len(zones)} zones from Rachio")

            # Collect recent events (last 24 hours)
            if not self.last_rachio_collection:
                # First run - get last 7 days of events
                events = self.rachio_client.get_recent_events(days=7)
            else:
                # Get events since last collection
                events = self.rachio_client.get_events(
                    self.last_rachio_collection, datetime.now()
                )

            if events:
                self.db.save_watering_events(events)
                self.logger.info(f"Collected {len(events)} watering events from Rachio")

            self.last_rachio_collection = datetime.now()

        except Exception as e:
            self.logger.error(f"Error collecting Rachio data: {e}")

    async def collect_flume_data(self) -> None:
        """Collect data from Flume API."""
        try:
            # Determine time range for collection
            if not self.last_flume_collection:
                # First run - get last 24 hours
                start_time = datetime.now() - timedelta(hours=24)
            else:
                # Get data since last collection
                start_time = self.last_flume_collection

            end_time = datetime.now()

            # Collect water readings
            readings = self.flume_client.get_usage(start_time, end_time, bucket="MIN")

            if readings:
                self.db.save_water_readings(readings)
                self.logger.info(f"Collected {len(readings)} water readings from Flume")

            self.last_flume_collection = end_time

        except Exception as e:
            self.logger.error(f"Error collecting Flume data: {e}")

    async def process_collected_data(self) -> None:
        """Process collected data to compute zone sessions and statistics."""
        try:
            # Compute zone sessions from watering events
            self.db.compute_zone_sessions()
            self.logger.info("Computed zone sessions from watering events")

        except Exception as e:
            self.logger.error(f"Error processing collected data: {e}")

    async def collect_once(self) -> None:
        """Run one collection cycle."""
        self.logger.info("Starting data collection cycle")

        # Collect from both APIs concurrently
        await asyncio.gather(
            self.collect_rachio_data(),
            self.collect_flume_data(),
            return_exceptions=True,
        )

        # Process the collected data
        await self.process_collected_data()

        self.logger.info("Data collection cycle completed")

    async def run_continuous(self) -> None:
        """Run continuous data collection."""
        self.logger.info(
            f"Starting continuous collection every {self.poll_interval} seconds"
        )

        while True:
            try:
                await self.collect_once()

                # Wait for next collection cycle
                await asyncio.sleep(self.poll_interval)

            except KeyboardInterrupt:
                self.logger.info("Collection stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in collection cycle: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(60)

    def get_current_status(self) -> dict:
        """Get current status of water tracking system."""
        try:
            # Get current active zone from Rachio
            active_zone = self.rachio_client.get_active_zone()

            # Get current water usage rate from Flume
            current_usage_rate = self.flume_client.get_current_usage_rate()

            # Get recent sessions from database
            recent_sessions = self.db.get_zone_sessions(
                datetime.now() - timedelta(hours=24), datetime.now()
            )

            return {
                "active_zone": {
                    "zone_number": active_zone.zone_number if active_zone else None,
                    "zone_name": active_zone.name if active_zone else None,
                },
                "current_usage_rate_gpm": current_usage_rate,
                "recent_sessions_count": len(recent_sessions),
                "last_rachio_collection": (
                    self.last_rachio_collection.isoformat()
                    if self.last_rachio_collection
                    else None
                ),
                "last_flume_collection": (
                    self.last_flume_collection.isoformat()
                    if self.last_flume_collection
                    else None
                ),
            }

        except Exception as e:
            self.logger.error(f"Error getting current status: {e}")
            return {"error": str(e)}
