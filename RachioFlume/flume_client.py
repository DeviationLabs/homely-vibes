"""Flume API client for water consumption monitoring."""

import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import requests
from pydantic import BaseModel


class WaterReading(BaseModel):
    """Water consumption reading."""

    timestamp: datetime
    value: float  # gallons consumed
    unit: str = "GAL"


class Device(BaseModel):
    """Flume device model."""

    id: str
    name: str
    location: Optional[str] = None
    active: bool = True


class FlumeClient:
    """Client for Flume water monitoring API."""

    BASE_URL = "https://api.flumetech.com"

    def __init__(
        self,
        access_token: Optional[str] = None,
        device_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize Flume client.

        Args:
            access_token: Flume access token (defaults to FLUME_ACCESS_TOKEN env var)
            device_id: Optional specific device ID (defaults to first active device)
            client_id: OAuth client ID (defaults to FLUME_CLIENT_ID env var)
            client_secret: OAuth client secret (defaults to FLUME_CLIENT_SECRET env var)
            username: Flume username (defaults to FLUME_USERNAME env var)
            password: Flume password (defaults to FLUME_PASSWORD env var)
        """
        self.access_token = access_token or os.getenv("FLUME_ACCESS_TOKEN")
        self._device_id = device_id or os.getenv("FLUME_DEVICE_ID")
        
        # OAuth credentials
        self.client_id = client_id or os.getenv("FLUME_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("FLUME_CLIENT_SECRET")
        self.username = username or os.getenv("FLUME_USERNAME")
        self.password = password or os.getenv("FLUME_PASSWORD")

        # If no access token provided, try to authenticate with credentials
        if not self.access_token:
            if not all([self.client_id, self.client_secret, self.username, self.password]):
                raise ValueError(
                    "Either access_token or all OAuth credentials (client_id, client_secret, username, password) are required"
                )
            self.access_token = self._get_access_token()

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # Cache for device info
        self._devices: Optional[List[Device]] = None
        self._primary_device_id: Optional[str] = None

    def _get_access_token(self) -> str:
        """Get access token using OAuth2 Resource Owner Credentials Grant."""
        url = "https://api.flumewater.com/oauth/token"
        
        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }
        
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        token_data = response.json()
        return token_data["access_token"]

    def get_devices(self) -> List[Device]:
        """Get all devices for the authenticated user."""
        if self._devices is not None:
            return self._devices

        url = f"{self.BASE_URL}/users/me/devices"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        devices_data = response.json()
        devices = []

        # Handle different possible response structures
        device_list = (
            devices_data
            if isinstance(devices_data, list)
            else devices_data.get("data", [])
        )

        for device_data in device_list:
            devices.append(
                Device(
                    id=device_data["id"],
                    name=device_data.get("name", "Unknown Device"),
                    location=device_data.get("location"),
                    active=device_data.get("active", True),
                )
            )

        self._devices = devices
        return devices

    def get_device_id(self) -> str:
        """Get the device ID to use for API calls.

        Returns the explicitly set device ID, or the first active device.
        """
        if self._device_id:
            return self._device_id

        if self._primary_device_id:
            return self._primary_device_id

        devices = self.get_devices()

        if not devices:
            raise ValueError("No Flume devices found for this account")

        # Find first active device
        for device in devices:
            if device.active:
                self._primary_device_id = device.id
                return device.id

        # Fallback to first device if none are marked active
        self._primary_device_id = devices[0].id
        return devices[0].id

    def get_usage(
        self, start_time: datetime, end_time: datetime, bucket: str = "MIN"
    ) -> List[WaterReading]:
        """Get water usage for a time range.

        Args:
            start_time: Start of time range
            end_time: End of time range
            bucket: Time bucket size (MIN, HR, DAY, MON, YR)

        Returns:
            List of water readings
        """
        device_id = self.get_device_id()
        url = f"{self.BASE_URL}/users/me/devices/{device_id}/query"

        # Format datetimes for Flume API
        start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            "queries": [
                {
                    "request_id": f"query_{int(datetime.now().timestamp())}",
                    "bucket": bucket,
                    "since_datetime": start_str,
                    "until_datetime": end_str,
                }
            ]
        }

        response = requests.post(url, json=payload, headers=self.headers)
        response.raise_for_status()

        readings = []
        data = response.json()

        # Parse response - structure may vary based on Flume API
        for query_result in data.get("data", []):
            for reading in query_result.get("data", []):
                timestamp = datetime.fromisoformat(
                    reading["datetime"].replace("Z", "+00:00")
                )
                value = float(reading["value"])

                readings.append(WaterReading(timestamp=timestamp, value=value))

        return readings

    def get_current_usage_rate(self) -> Optional[float]:
        """Get current water usage rate in gallons per minute."""
        # Get usage for last 5 minutes
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=5)

        readings = self.get_usage(start_time, end_time, bucket="MIN")

        if not readings:
            return None

        # Calculate average rate from recent readings
        total_usage = sum(r.value for r in readings)
        time_span_minutes = len(readings)

        return total_usage / time_span_minutes if time_span_minutes > 0 else 0.0

    def get_usage_for_period(self, start_time: datetime, end_time: datetime) -> float:
        """Get total water usage for a specific time period.

        Args:
            start_time: Start of period
            end_time: End of period

        Returns:
            Total gallons used in the period
        """
        readings = self.get_usage(start_time, end_time, bucket="MIN")
        return sum(r.value for r in readings)

    def get_daily_usage(self, date: datetime) -> List[WaterReading]:
        """Get hourly water usage for a specific day."""
        start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=1)

        return self.get_usage(start_time, end_time, bucket="HR")

    def get_recent_usage(self, hours: int = 24) -> List[WaterReading]:
        """Get water usage from the last N hours."""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

        return self.get_usage(start_time, end_time, bucket="MIN")
