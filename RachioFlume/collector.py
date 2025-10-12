"""Data collection service that polls Rachio and Flume APIs."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from .rachio_client import RachioClient
from .flume_client import FlumeClient
from .data_storage import WaterTrackingDB
from lib.logger import get_logger


class WaterTrackingCollector:
    """Service that collects data from Rachio and Flume APIs."""

    def __init__(self, db_path: str, poll_interval_seconds: int = 300):  # 5 minutes default
        self.logger = get_logger(__name__)

        self.db = WaterTrackingDB(db_path)
        self.rachio_client = RachioClient()
        self.flume_client = FlumeClient()
        self.poll_interval = poll_interval_seconds

        # Initialize last collection times from database to avoid duplicates
        self.last_rachio_collection: Optional[datetime] = self.db.get_last_collection_timestamp(
            "rachio"
        )
        self.last_flume_collection: Optional[datetime] = self.db.get_last_collection_timestamp(
            "flume"
        )

        if self.last_rachio_collection:
            self.logger.info(
                f"Initialized with last Rachio collection: {self.last_rachio_collection}"
            )
        if self.last_flume_collection:
            self.logger.info(
                f"Initialized with last Flume collection: {self.last_flume_collection}"
            )

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
                events = self.rachio_client.get_events(self.last_rachio_collection, datetime.now())

            if events:
                # Filter out events that overlap with existing data
                filtered_events = self._filter_duplicate_events(events)
                if filtered_events:
                    self.db.save_watering_events(filtered_events)
                    self.logger.info(
                        f"Collected {len(filtered_events)} new watering events from Rachio ({len(events) - len(filtered_events)} duplicates filtered)"
                    )
                else:
                    self.logger.info(
                        f"No new events after filtering {len(events)} duplicates from Rachio"
                    )

            collection_time = datetime.now()
            self.last_rachio_collection = collection_time
            # Save collection timestamp to database for persistence
            self.db.set_last_collection_timestamp("rachio", collection_time)

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
                # Filter out readings that overlap with existing data
                filtered_readings = self._filter_duplicate_readings(readings)
                if filtered_readings:
                    self.db.save_water_readings(filtered_readings)
                    self.logger.info(
                        f"Collected {len(filtered_readings)} new water readings from Flume ({len(readings) - len(filtered_readings)} duplicates filtered)"
                    )
                else:
                    self.logger.info(
                        f"No new readings after filtering {len(readings)} duplicates from Flume"
                    )

            self.last_flume_collection = end_time
            # Save collection timestamp to database for persistence
            self.db.set_last_collection_timestamp("flume", end_time)

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
        self.logger.info(f"Starting continuous collection every {self.poll_interval} seconds")

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

    def get_current_status(self) -> Dict[str, Any]:
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
                    self.last_rachio_collection.isoformat() if self.last_rachio_collection else None
                ),
                "last_flume_collection": (
                    self.last_flume_collection.isoformat() if self.last_flume_collection else None
                ),
            }

        except Exception as e:
            self.logger.error(f"Error getting current status: {e}")
            return {"error": str(e)}

    def _filter_duplicate_events(self, events: List[Any]) -> List[Any]:
        """Filter out watering events that already exist in the database."""
        if not events:
            return events

        # Get the last data timestamp from the database
        last_data_timestamp = self.db.get_last_data_timestamp("rachio")

        if not last_data_timestamp:
            # No existing data, return all events
            return events

        # Filter out events that are at or before the last timestamp
        filtered_events = []
        for event in events:
            # Assuming the event has an event_date attribute
            if hasattr(event, "event_date") and event.event_date > last_data_timestamp:
                filtered_events.append(event)

        return filtered_events

    def _filter_duplicate_readings(self, readings: List[Any]) -> List[Any]:
        """Filter out water readings that already exist in the database."""
        if not readings:
            return readings

        # Get the last data timestamp from the database
        last_data_timestamp = self.db.get_last_data_timestamp("flume")

        if not last_data_timestamp:
            # No existing data, return all readings
            return readings

        # Filter out readings that are at or before the last timestamp
        filtered_readings = []
        for reading in readings:
            # Assuming the reading has a timestamp attribute
            if hasattr(reading, "timestamp") and reading.timestamp > last_data_timestamp:
                filtered_readings.append(reading)

        return filtered_readings
