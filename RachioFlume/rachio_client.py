"""Rachio API client for zone monitoring and watering events."""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import requests
from pydantic import BaseModel

from lib.logger import get_logger
from lib import Constants


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
            api_key: Rachio API key (defaults to Constants.RACHIO_API_KEY)
            device_id: Rachio device ID (defaults to Constants.RACHIO_ID)
        """
        self.api_key = api_key or Constants.RACHIO_API_KEY
        self.device_id = device_id or Constants.RACHIO_ID

        if not self.api_key:
            raise ValueError("Rachio API key required")
        if not self.device_id:
            raise ValueError("Rachio device ID required")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Setup logging
        self.logger = get_logger(__name__)
        self.logger.info(f"Rachio client initialized for device {self.device_id}")

    def get_device_info(self) -> Dict[str, Any]:
        """Get device information including zones."""
        url = f"{self.BASE_URL}/device/{self.device_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        device_info = response.json()
        self.logger.info(
            f"Retrieved device info for {device_info.get('name', 'Unknown Device')}"
        )
        return device_info

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
        self.logger.info(f"Found {len(zones)} zones: {[z.name for z in zones]}")
        return zones

    def get_active_zone(self) -> Optional[Zone]:
        """Get currently active watering zone."""
        try:
            # Check current schedule execution status
            url = f"{self.BASE_URL}/device/{self.device_id}/current_schedule"
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                current_schedule = response.json()
                
                # If status is PROCESSING, there's an active zone
                if current_schedule.get("status") == "PROCESSING":
                    zone_id = current_schedule.get("zoneId")
                    zone_number = current_schedule.get("zoneNumber")
                    
                    if zone_id and zone_number:
                        # Get zone details from device info
                        device_info = self.get_device_info()
                        for zone_data in device_info.get("zones", []):
                            if zone_data["id"] == zone_id:
                                return Zone(
                                    id=zone_data["id"],
                                    zone_number=zone_data["zoneNumber"],
                                    name=zone_data["name"],
                                    enabled=zone_data["enabled"],
                                )
            elif response.status_code == 204:
                # No current schedule running
                pass
                
        except Exception as e:
            self.logger.error(f"Error checking current schedule: {e}")
        
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
        self.logger.info(f"Fetching watering events from {start_time} to {end_time}")
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
            # Parse zone name and number from summary (e.g., "Z5 BBS - flowers ...")
            summary = event_data.get("summary", "")
            zone_name = summary.split("-")[0].split("(")[0].strip()

            # Extract zone number from summary (e.g., "Z5" -> 5)
            zone_number = -1
            if zone_name.startswith("Z") and len(zone_name) > 1:
                try:
                    # Extract number from "Z5 BBS" format
                    zone_part = zone_name.split()[0]  # Get "Z5"
                    if zone_part[1:].isdigit():
                        zone_number = int(zone_part[1:])
                except (IndexError, ValueError):
                    zone_number = -1

            event = WateringEvent(
                event_date=datetime.fromtimestamp(event_data["eventDate"] / 1000),
                zone_name=zone_name,
                zone_number=zone_number,
                event_type=event_data.get("subType", "UNKNOWN"),
                duration_seconds=event_data.get("durationSeconds"),
            )
            events.append(event)

        self.logger.info(f"Retrieved {len(events)} watering events")
        return events

    def get_recent_events(self, days: int = 7) -> List[WateringEvent]:
        """Get watering events from the last N days."""
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        return self.get_events(start_time, end_time)
