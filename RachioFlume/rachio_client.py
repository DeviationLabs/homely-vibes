"""Rachio API client for zone monitoring and watering events."""

import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import requests
from pydantic import BaseModel


class Zone(BaseModel):
    """Rachio zone model."""

    id: str
    zone_number: int
    name: str
    enabled: bool


class WateringEvent(BaseModel):
    """Rachio watering event model."""

    event_date: datetime
    zone_name: str
    zone_number: int
    event_type: str  # ZONE_STARTED, ZONE_COMPLETED, ZONE_STOPPED
    duration_seconds: Optional[int] = None


class RachioClient:
    """Client for Rachio irrigation system API."""

    BASE_URL = "https://api.rach.io/1/public"

    def __init__(self, api_key: Optional[str] = None, device_id: Optional[str] = None):
        """Initialize Rachio client.

        Args:
            api_key: Rachio API key (defaults to RACHIO_API_KEY env var)
            device_id: Rachio device ID (defaults to RACHIO_ID env var)
        """
        self.api_key = api_key or os.getenv("RACHIO_API_KEY")
        self.device_id = device_id or os.getenv("RACHIO_ID")

        if not self.api_key:
            raise ValueError("Rachio API key required")
        if not self.device_id:
            raise ValueError("Rachio device ID required")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_device_info(self) -> Dict[str, Any]:
        """Get device information including zones."""
        url = f"{self.BASE_URL}/device/{self.device_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_zones(self) -> List[Zone]:
        """Get all zones for the device."""
        device_info = self.get_device_info()
        zones = []
        for zone_data in device_info.get("zones", []):
            zones.append(
                Zone(
                    id=zone_data["id"],
                    zone_number=zone_data["zoneNumber"],
                    name=zone_data["name"],
                    enabled=zone_data["enabled"],
                )
            )
        return zones

    def get_active_zone(self) -> Optional[Zone]:
        """Get currently active watering zone."""
        device_info = self.get_device_info()

        # Check if any schedule is running
        for schedule in device_info.get("scheduleRules", []):
            if schedule.get("enabled", False):
                # This is a simplified check - in practice you'd need to check
                # current schedule execution status
                pass

        # For now, return None if no zone is active
        # Real implementation would check current watering status
        return None

    def get_events(
        self, start_time: datetime, end_time: datetime
    ) -> List[WateringEvent]:
        """Get watering events for a time range.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            List of watering events
        """
        url = f"{self.BASE_URL}/device/{self.device_id}/event"

        # Convert to milliseconds since epoch
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        params = {
            "startTime": start_ms,
            "endTime": end_ms,
            "type": "ZONE_STATUS",
            "topic": "WATERING",
        }

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        events = []
        for event_data in response.json():
            # Parse zone name from summary
            summary = event_data.get("summary", "")
            zone_name = summary.split("-")[0].split("(")[0].strip()

            # Extract zone number from event data
            zone_number = event_data.get("zoneNumber", -1)

            event = WateringEvent(
                event_date=datetime.fromtimestamp(event_data["eventDate"] / 1000),
                zone_name=zone_name,
                zone_number=zone_number,
                event_type=event_data["subType"],
                duration_seconds=event_data.get("durationSeconds"),
            )
            events.append(event)

        return events

    def get_recent_events(self, days: int = 7) -> List[WateringEvent]:
        """Get watering events from the last N days."""
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        return self.get_events(start_time, end_time)
