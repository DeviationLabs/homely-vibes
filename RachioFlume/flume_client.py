"""Flume API client for water consumption monitoring."""

from datetime import datetime, timedelta
from typing import Any, Optional, List
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
    """Client for Flume water monitoring API.

    Access tokens expire (Flume default: 7 days). Long-running callers (the
    collector daemon) go through `_request`, which re-authenticates
    proactively near expiry and reactively on a 401 — a token fetched once in
    `__init__` and never refreshed is exactly the failure mode that blinded
    the collector for 6 days in July 2026.
    """

    BASE_URL = "https://api.flumewater.com"
    DEFAULT_TOKEN_LIFETIME_SECONDS = 604800  # Flume default: 7 days
    # Refresh proactively at 90% of lifetime so a mid-request expiry is rare.
    TOKEN_REFRESH_FRACTION = 0.9

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.logger = get_logger(__name__)

        # OAuth credentials
        self.client_id = client_id or cfg.flume.client_id
        self.client_secret = client_secret or cfg.flume.client_secret
        self.username = username or cfg.flume.user_email
        self.password = password or cfg.flume.password

        # Injectable for tests (no patch()) and shared connection pooling.
        self.session = session or requests.Session()

        self._token_acquired_at = datetime.min
        self._token_lifetime_seconds = float(self.DEFAULT_TOKEN_LIFETIME_SECONDS)
        self._authenticate()

        # Cache for device info
        self._devices: Optional[List[Device]] = None

    def _authenticate(self) -> None:
        """(Re)acquire an access token and rebuild request headers."""
        self.logger.info(f"Authenticating with Flume API using OAuth2 for user: {self.username}")

        url = f"{self.BASE_URL}/oauth/token?envelope=true"

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
            response = self.session.post(url, json=payload, headers=headers)
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

            self.access_token = str(access_token)
            self._token_acquired_at = datetime.now()
            self._token_lifetime_seconds = float(
                token_info.get("expires_in") or self.DEFAULT_TOKEN_LIFETIME_SECONDS
            )
            self.headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
            self.logger.info("Successfully obtained access token from Flume API")
        except requests.RequestException as e:
            self.logger.error(f"Failed to authenticate with Flume API: {e}")
            if hasattr(e, "response") and e.response is not None:
                self.logger.error(f"Response status: {e.response.status_code}")
                self.logger.error(f"Response body: {e.response.text}")
            raise

    def _token_is_stale(self) -> bool:
        age = (datetime.now() - self._token_acquired_at).total_seconds()
        return age >= self.TOKEN_REFRESH_FRACTION * self._token_lifetime_seconds

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Issue an authenticated request, refreshing the token as needed.

        Proactive: re-auth when past TOKEN_REFRESH_FRACTION of the token
        lifetime. Reactive: on a 401, re-auth once and retry — covers early
        revocation and wall-clock drift. Raises for status on the final
        response either way.
        """
        if self._token_is_stale():
            self.logger.info("Flume access token near expiry; re-authenticating proactively")
            self._authenticate()

        response = self.session.request(method, url, headers=self.headers, **kwargs)
        if response.status_code == 401:
            self.logger.warning("Flume API returned 401; re-authenticating and retrying once")
            self._authenticate()
            response = self.session.request(method, url, headers=self.headers, **kwargs)
        response.raise_for_status()
        return response

    def get_devices(self) -> List[Device]:
        """Get all devices for the authenticated user."""
        if self._devices is not None:
            return self._devices

        # Use /me/devices format per API behavior
        url = f"{self.BASE_URL}/me/devices"
        response = self._request("GET", url)

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
                    loc_response = self._request("GET", loc_url)
                    if loc_response.status_code == 200:
                        loc_data = loc_response.json()
                        loc_info = loc_data.get("data", [])
                        if loc_info and isinstance(loc_info, list):
                            location_name = loc_info[0].get("name", "Home")
                except Exception:
                    pass  # Fall back to default naming

        # Flume API enumerates type=1 (Wi-Fi bridge — relay only, no flow)
        # and type=2 (water sensor — the actual meter). Bridges always report
        # value=0 every minute, which used to produce duplicate-zero rows in
        # water_readings and inflate-CV the engine's sustained-flow predicate
        # into rejecting genuine multi-fixture events (e.g. a shower at
        # 2.4 GPM showing as `[2.4, 0.0, 2.4, 0.0, ...]` after interleave).
        # Skip non-meter device types entirely.
        devices = []
        skipped = 0
        for device_data in device_list:
            device_type = device_data.get("type", 0)
            if device_type != 2:
                skipped += 1
                self.logger.debug(
                    f"Skipping non-meter Flume device id={device_data.get('id')} type={device_type}"
                )
                continue
            devices.append(
                Device(
                    id=device_data["id"],
                    name=f"{location_name or 'Flume'} Water Sensor",
                    location=location_name,
                    active=device_data.get("connected", True),
                )
            )

        self._devices = devices
        self.logger.info(
            f"Found {len(devices)} Flume water meters "
            f"(skipped {skipped} non-meter devices): {[d.name for d in devices]}"
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
                response = self._request("POST", url, json=payload)

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

        # Aggregate per-minute across all meters (sum). With one water meter
        # this is a no-op deduplication; with multiple meters at the same
        # location it gives the engine a single coherent flow series instead
        # of N interleaved per-device rows. Sum is the correct combinator
        # because each meter measures a disjoint physical sub-flow.
        # Round timestamps to the minute before merging so sub-second drift
        # between per-device responses doesn't escape the dedup.
        merged: dict[datetime, float] = {}
        for r in all_readings:
            minute_key = r.timestamp.replace(second=0, microsecond=0)
            merged[minute_key] = merged.get(minute_key, 0.0) + r.value
        deduped = [WaterReading(timestamp=ts, value=v) for ts, v in sorted(merged.items())]
        if len(deduped) != len(all_readings):
            self.logger.debug(
                f"Merged {len(all_readings)} per-device rows → {len(deduped)} per-minute rows"
            )
        self.logger.info(f"Retrieved {len(deduped)} per-minute water readings")
        return deduped

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
