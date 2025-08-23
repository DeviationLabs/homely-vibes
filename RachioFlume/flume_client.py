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


class FlumeClient:
    """Client for Flume water monitoring API."""

    BASE_URL = "https://api.flumetech.com"

    def __init__(
        self,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        """Initialize Flume client.

        Args:
            user_id: Flume user ID (defaults to FLUME_USER_ID env var)
            device_id: Flume device ID (defaults to FLUME_DEVICE_ID env var)
            access_token: Flume access token (defaults to FLUME_ACCESS_TOKEN env var)
        """
        self.user_id = user_id or os.getenv("FLUME_USER_ID")
        self.device_id = device_id or os.getenv("FLUME_DEVICE_ID")
        self.access_token = access_token or os.getenv("FLUME_ACCESS_TOKEN")

        if not all([self.user_id, self.device_id, self.access_token]):
            raise ValueError("Flume user_id, device_id, and access_token required")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

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
        url = f"{self.BASE_URL}/users/{self.user_id}/devices/{self.device_id}/query"

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
