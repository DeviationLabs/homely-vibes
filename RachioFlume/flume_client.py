"""Flume API client for water consumption monitoring."""

from datetime import datetime, timedelta
from typing import Optional, List
import requests
from pydantic import BaseModel
from lib.logger import get_logger
from lib.config import get_config


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


cfg = get_config()


class FlumeClient:
    """Client for Flume water monitoring API."""

    BASE_URL = "https://api.flumewater.com"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.logger = get_logger(__name__)

        # OAuth credentials
        self.client_id = client_id or cfg.flume.client_id
        self.client_secret = client_secret or cfg.flume.client_secret
        self.username = username or cfg.flume.user_email
        self.password = password or cfg.flume.password

        self.access_token = self._get_access_token()

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # Cache for device info
        self._devices: Optional[List[Device]] = None

    def _get_access_token(self) -> str:
        """Get access token using OAuth2 Resource Owner Credentials Grant."""
        self.logger.info(f"Authenticating with Flume API using OAuth2 for user: {self.username}")

        url = "https://api.flumewater.com/oauth/token?envelope=true"

        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            response_data = response.json()

            # Check API success status
            if not response_data.get("success", True):
                error_msg = response_data.get(
                    "detailed",
                    response_data.get("message", "Authentication failed"),
                )
                raise ValueError(f"Flume API error: {error_msg}")

            # Extract token from data array (per Flume API documentation)
            data_array = response_data.get("data", [])
            if not data_array or not isinstance(data_array, list):
                raise ValueError("No token data returned from Flume API")

            token_info = data_array[0]
            access_token: Optional[str] = token_info.get("access_token")
            if not access_token:
                raise ValueError("No access_token found in Flume API response")

            self.logger.info("Successfully obtained access token from Flume API")
            return str(access_token)
        except requests.RequestException as e:
            self.logger.error(f"Failed to authenticate with Flume API: {e}")
            if hasattr(e, "response") and e.response is not None:
                self.logger.error(f"Response status: {e.response.status_code}")
                self.logger.error(f"Response body: {e.response.text}")
            raise

    def get_devices(self) -> List[Device]:
        """Get all devices for the authenticated user."""
        if self._devices is not None:
            return self._devices

        # Use /me/devices format per API behavior
        url = f"{self.BASE_URL}/me/devices"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        response_data = response.json()

        # Check API success status
        if not response_data.get("success", True):
            error_msg = response_data.get(
                "detailed",
                response_data.get("message", "Failed to get devices"),
            )
            raise ValueError(f"Flume API error: {error_msg}")

        # Extract devices from data array
        device_list = response_data.get("data", [])
        if not isinstance(device_list, list):
            raise ValueError("Invalid device data format from Flume API")

        # Get location name for better device naming
        location_name = None
        if device_list:
            location_id = device_list[0].get("location_id")
            if location_id:
                try:
                    loc_url = f"{self.BASE_URL}/me/locations/{location_id}"
                    loc_response = requests.get(loc_url, headers=self.headers)
                    if loc_response.status_code == 200:
                        loc_data = loc_response.json()
                        loc_info = loc_data.get("data", [])
                        if loc_info and isinstance(loc_info, list):
                            location_name = loc_info[0].get("name", "Home")
                except Exception:
                    pass  # Fall back to default naming

        devices = []
        for device_data in device_list:
            # Create meaningful device names based on type and location
            device_type = device_data.get("type", 0)
            product = device_data.get("product", "flume")

            if device_type == 1:
                # Type 1 is typically the bridge/hub
                device_name = f"{location_name or 'Flume'} Bridge"
            elif device_type == 2:
                # Type 2 is typically the water sensor
                device_name = f"{location_name or 'Flume'} Water Sensor"
            else:
                device_name = f"{location_name or 'Flume'} Device ({product})"

            devices.append(
                Device(
                    id=device_data["id"],
                    name=device_name,
                    location=location_name,
                    active=device_data.get("connected", True),
                )
            )

        self._devices = devices
        self.logger.info(f"Found {len(devices)} Flume devices: {[d.name for d in devices]}")
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
            url = f"{self.BASE_URL}/me/devices/{device.id}/query"

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

                # Parse response - Flume API returns data keyed by request_id
                for query_result in data.get("data", []):
                    # Each query_result is a dict with request_id as key
                    for _, reading_list in query_result.items():
                        if isinstance(reading_list, list):
                            for reading in reading_list:
                                # Parse datetime - Flume returns "YYYY-MM-DD HH:MM:SS" format
                                datetime_str = reading["datetime"]
                                timestamp = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                                value = float(reading["value"])

                                all_readings.append(WaterReading(timestamp=timestamp, value=value))

            except requests.RequestException as e:
                # Log error but continue with other devices
                self.logger.error(
                    f"Failed to get usage for device {device.name} ({device.id}): {e}"
                )
                continue

        # Sort readings by timestamp
        all_readings.sort(key=lambda x: x.timestamp)
        self.logger.info(f"Retrieved {len(all_readings)} total water readings across all devices")
        return all_readings

    def get_current_usage_rate(self) -> Optional[float]:
        """Get current water usage rate across all devices in gallons per minute."""
        # Get usage for last 5 minutes
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=3)

        readings = self.get_usage(start_time, end_time, bucket="MIN")

        if not readings:
            return None

        # Each reading is already in GPM (gallons per minute)
        # Find the most recent non-zero reading, or average recent non-zero readings
        non_zero_readings = [r.value for r in readings if r.value > 0]

        if not non_zero_readings:
            return 0.0

        # Use average of recent non-zero readings for stability
        return sum(non_zero_readings) / len(non_zero_readings)

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
