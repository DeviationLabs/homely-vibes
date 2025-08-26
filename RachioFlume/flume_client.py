"""Flume API client for water consumption monitoring."""

import os
from datetime import datetime, timedelta
from typing import Optional, List
import requests
from pydantic import BaseModel

from lib.logger import get_logger


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
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize Flume client.

        Args:
            client_id: OAuth client ID (defaults to FLUME_CLIENT_ID env var)
            client_secret: OAuth client secret (defaults to FLUME_CLIENT_SECRET env var)
            username: Flume email address (defaults to FLUME_USER_EMAIL env var)
            password: Flume password (defaults to FLUME_PASSWORD env var)
        """
        # Setup logging first
        self.logger = get_logger(__name__)

        # OAuth credentials
        self.client_id = client_id or os.getenv("FLUME_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("FLUME_CLIENT_SECRET")
        self.username = username or os.getenv("FLUME_USER_EMAIL")
        self.password = password or os.getenv("FLUME_PASSWORD")

        if not all([self.client_id, self.client_secret, self.username, self.password]):
            missing = []
            if not self.client_id: missing.append("FLUME_CLIENT_ID")
            if not self.client_secret: missing.append("FLUME_CLIENT_SECRET")
            if not self.username: missing.append("FLUME_USER_EMAIL")
            if not self.password: missing.append("FLUME_PASSWORD")
            raise ValueError(
                f"Missing required Flume credentials: {', '.join(missing)}. "
                "Please check your environment variables."
            )

        self.access_token = self._get_access_token()

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # Cache for device info
        self._devices: Optional[List[Device]] = None
        
    def test_credentials(self) -> dict:
        """Test if credentials are properly configured without making API calls.
        
        Returns:
            Dict with credential validation results
        """
        results = {
            "client_id_set": bool(self.client_id),
            "client_secret_set": bool(self.client_secret), 
            "username_set": bool(self.username),
            "password_set": bool(self.password),
            "all_credentials_present": bool(all([self.client_id, self.client_secret, self.username, self.password]))
        }
        
        if results["all_credentials_present"] and self.client_id and self.username:
            results["client_id_preview"] = f"{self.client_id[:8]}..." if len(self.client_id) > 8 else self.client_id
            results["username_preview"] = self.username
        
        return results

    def _get_access_token(self) -> str:
        """Get access token using OAuth2 Resource Owner Credentials Grant."""
        self.logger.info(f"Authenticating with Flume API using OAuth2 for user: {self.username}")
        self.logger.debug(f"Using client_id: {self.client_id[:8] if self.client_id else 'None'}...")
        
        url = "https://api.flumewater.com/oauth/token"

        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,  # API error shows it expects username parameter
            "password": self.password,
        }

        headers = {"Content-Type": "application/json"}
        
        # Log request details for debugging
        self.logger.debug(f"Request URL: {url}")
        self.logger.debug(f"Payload structure: grant_type={payload.get('grant_type')}, username={'***' if self.username else 'None'}, password={'***' if self.password else 'None'}")
        self.logger.debug(f"Request headers: {headers}")

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            token_data = response.json()
            self.logger.info("Successfully obtained access token from Flume API")
            self.logger.debug(f"Access token length: {len(token_data['access_token'])} characters")
            return token_data["access_token"]
        except requests.RequestException as e:
            self.logger.error(f"Failed to authenticate with Flume API: {e}")
            if hasattr(e, "response") and e.response is not None:
                self.logger.error(f"Response status: {e.response.status_code}")
                self.logger.error(f"Response body: {e.response.text}")
                
                # Parse error response for better debugging
                try:
                    error_data = e.response.json()
                    if "detailed" in error_data:
                        self.logger.error(f"API error details: {error_data['detailed']}")
                    
                    # Check for credential-specific errors
                    if error_data.get("message") == "invalid_grant":
                        self.logger.error(
                            "Credential validation failed. Please verify:\n"
                            "1. FLUME_USER_EMAIL is correct (should be your Flume login email)\n"
                            "2. FLUME_PASSWORD is correct\n"
                            "3. FLUME_CLIENT_ID and FLUME_CLIENT_SECRET are valid OAuth credentials\n"
                            "4. Your Flume account has API access enabled"
                        )
                except Exception:
                    pass  # If we can't parse the response, just continue
            raise

    def get_devices(self) -> List[Device]:
        """Get all devices for the authenticated user."""
        if self._devices is not None:
            self.logger.debug("Returning cached device list")
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
        self.logger.info(
            f"Found {len(devices)} Flume devices: {[d.name for d in devices]}"
        )
        return devices

    def get_usage(
        self, start_time: datetime, end_time: datetime, bucket: str = "MIN"
    ) -> List[WaterReading]:
        """Get water usage for a time range across all devices.

        Args:
            start_time: Start of time range
            end_time: End of time range
            bucket: Time bucket size (MIN, HR, DAY, MON, YR)

        Returns:
            List of water readings from all devices
        """
        devices = self.get_devices()
        if not devices:
            raise ValueError("No Flume devices found for this account")

        all_readings = []

        # Format datetimes for Flume API
        start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        self.logger.info(
            f"Querying usage data from {len(devices)} devices for period {start_str} to {end_str}"
        )

        for device in devices:
            url = f"{self.BASE_URL}/users/me/devices/{device.id}/query"

            payload = {
                "queries": [
                    {
                        "request_id": f"query_{device.id}_{int(datetime.now().timestamp())}",
                        "bucket": bucket,
                        "since_datetime": start_str,
                        "until_datetime": end_str,
                    }
                ]
            }

            try:
                response = requests.post(url, json=payload, headers=self.headers)
                response.raise_for_status()

                data = response.json()

                # Parse response - structure may vary based on Flume API
                for query_result in data.get("data", []):
                    for reading in query_result.get("data", []):
                        timestamp = datetime.fromisoformat(
                            reading["datetime"].replace("Z", "+00:00")
                        )
                        value = float(reading["value"])

                        all_readings.append(
                            WaterReading(timestamp=timestamp, value=value)
                        )

            except requests.RequestException as e:
                # Log error but continue with other devices
                self.logger.error(
                    f"Failed to get usage for device {device.name} ({device.id}): {e}"
                )
                continue

        # Sort readings by timestamp
        all_readings.sort(key=lambda x: x.timestamp)
        self.logger.info(
            f"Retrieved {len(all_readings)} total water readings across all devices"
        )
        return all_readings

    def get_current_usage_rate(self) -> Optional[float]:
        """Get current water usage rate across all devices in gallons per minute."""
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
        """Get total water usage for a specific time period across all devices.

        Args:
            start_time: Start of period
            end_time: End of period

        Returns:
            Total gallons used in the period across all devices
        """
        readings = self.get_usage(start_time, end_time, bucket="MIN")
        return sum(r.value for r in readings)

    def get_daily_usage(self, date: datetime) -> List[WaterReading]:
        """Get hourly water usage for a specific day across all devices."""
        start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=1)

        return self.get_usage(start_time, end_time, bucket="HR")

    def get_recent_usage(self, hours: int = 24) -> List[WaterReading]:
        """Get water usage from the last N hours across all devices."""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

        return self.get_usage(start_time, end_time, bucket="MIN")
