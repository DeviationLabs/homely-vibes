"""Tests for the Rachio-Flume water tracking integration."""

import pytest
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch
import os

from lib import Constants
from RachioFlume.rachio_client import RachioClient, Zone, WateringEvent
from RachioFlume.flume_client import FlumeClient, WaterReading
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.collector import WaterTrackingCollector
from RachioFlume.reporter import WeeklyReporter


class TestRachioClient:
    """Test Rachio API client."""

    @patch.object(Constants, "RACHIO_API_KEY", "test_key")
    @patch.object(Constants, "RACHIO_ID", "test_device")
    def test_init_with_env_vars(self) -> None:
        """Test initialization with environment variables."""
        client = RachioClient()
        assert client.api_key == "test_key"
        assert client.device_id == "test_device"

    @patch.object(Constants, "RACHIO_API_KEY", None)
    @patch.object(Constants, "RACHIO_ID", None)
    def test_init_missing_credentials(self) -> None:
        """Test initialization fails without credentials."""
        with pytest.raises(ValueError, match="Rachio API key required"):
            RachioClient()

    @patch("RachioFlume.rachio_client.requests.get")
    @patch.object(Constants, "RACHIO_API_KEY", "test_key")
    @patch.object(Constants, "RACHIO_ID", "test_device")
    def test_get_zones(self, mock_get: Mock) -> None:
        """Test getting zones from device."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "zones": [
                {
                    "id": "zone1",
                    "zoneNumber": 1,
                    "name": "Front Yard",
                    "enabled": True,
                },
                {
                    "id": "zone2",
                    "zoneNumber": 2,
                    "name": "Back Yard",
                    "enabled": False,
                },
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = RachioClient()
        zones = client.get_zones()

        assert len(zones) == 2
        assert zones[0].name == "Front Yard"
        assert zones[0].zone_number == 1
        assert zones[0].enabled is True
        assert zones[1].name == "Back Yard"
        assert zones[1].enabled is False


class TestFlumeClient:
    """Test Flume API client."""

    @patch.object(Constants, "FLUME_CLIENT_ID", "client123")
    @patch.object(Constants, "FLUME_CLIENT_SECRET", "secret456")
    @patch.object(Constants, "FLUME_USER_EMAIL", "test@example.com")
    @patch.object(Constants, "FLUME_PASSWORD", "password789")
    @patch.object(FlumeClient, "_get_access_token", return_value="token123")
    def test_init_with_env_vars(self, _mock_token: Mock) -> None:
        """Test initialization with environment variables."""
        client = FlumeClient()
        assert client.client_id == "client123"
        assert client.client_secret == "secret456"
        assert client.username == "test@example.com"
        assert client.password == "password789"

    def test_init_missing_credentials(self) -> None:
        """Test initialization fails without credentials."""
        with pytest.raises(Exception):  # Will fail on missing OAuth credentials
            FlumeClient()

    @patch.object(Constants, "FLUME_PASSWORD", "password789")
    @patch.object(Constants, "FLUME_USER_EMAIL", "test@example.com")
    @patch.object(Constants, "FLUME_CLIENT_SECRET", "secret456")
    @patch.object(Constants, "FLUME_CLIENT_ID", "client123")
    @patch.object(FlumeClient, "_get_access_token", return_value="token123")
    @patch("RachioFlume.flume_client.requests.post")
    @patch("RachioFlume.flume_client.requests.get")
    def test_get_usage(self, mock_get: Mock, mock_post: Mock, *args: Mock) -> None:
        """Test getting water usage data."""
        client = FlumeClient()

        # Mock devices response
        devices_response = Mock()
        devices_response.json.return_value = {
            "success": True,
            "data": [{"id": "device456", "connected": True, "type": 2}],
        }
        devices_response.raise_for_status.return_value = None
        devices_response.status_code = 200

        # Mock location response (optional call)
        location_response = Mock()
        location_response.status_code = 404

        mock_get.side_effect = [devices_response, location_response]

        # Mock usage data response
        mock_usage_response = Mock()
        mock_usage_response.json.return_value = {
            "data": [
                {
                    "data": [
                        {"datetime": "2023-01-01 10:00:00", "value": 1.5},
                        {"datetime": "2023-01-01 10:01:00", "value": 2.0},
                    ]
                }
            ]
        }
        mock_usage_response.raise_for_status.return_value = None
        mock_post.return_value = mock_usage_response

        start_time = datetime(2023, 1, 1, 10, 0)
        end_time = datetime(2023, 1, 1, 10, 2)

        readings = client.get_usage(start_time, end_time)

        assert len(readings) == 2
        assert readings[0].value == 1.5
        assert readings[1].value == 2.0

    @patch.object(Constants, "FLUME_PASSWORD", "password789")
    @patch.object(Constants, "FLUME_USER_EMAIL", "test@example.com")
    @patch.object(Constants, "FLUME_CLIENT_SECRET", "secret456")
    @patch.object(Constants, "FLUME_CLIENT_ID", "client123")
    @patch.object(FlumeClient, "_get_access_token", return_value="token123")
    @patch("RachioFlume.flume_client.requests.get")
    def test_get_devices(self, mock_get: Mock, *args: Mock) -> None:
        """Test getting user devices."""
        client = FlumeClient()

        # Mock devices response
        devices_response = Mock()
        devices_response.json.return_value = {
            "success": True,
            "data": [
                {"id": "device1", "type": 2, "connected": True},
                {"id": "device2", "type": 2, "connected": False},
            ],
        }
        devices_response.raise_for_status.return_value = None
        devices_response.status_code = 200

        # Mock location response (optional call)
        location_response = Mock()
        location_response.status_code = 404  # Location not found, will use default names

        mock_get.side_effect = [devices_response, location_response]

        devices = client.get_devices()

        assert len(devices) == 2
        assert devices[0].id == "device1"
        assert "Water Sensor" in devices[0].name
        assert devices[0].active is True
        assert devices[1].id == "device2"
        assert "Water Sensor" in devices[1].name
        assert devices[1].active is False

    @patch.object(Constants, "FLUME_PASSWORD", "password789")
    @patch.object(Constants, "FLUME_USER_EMAIL", "test@example.com")
    @patch.object(Constants, "FLUME_CLIENT_SECRET", "secret456")
    @patch.object(Constants, "FLUME_CLIENT_ID", "client123")
    @patch.object(FlumeClient, "_get_access_token", return_value="token123")
    @patch("RachioFlume.flume_client.requests.get")
    def test_get_active_device(self, mock_get: Mock, *args: Mock) -> None:
        """Test getting active device from device list."""
        client = FlumeClient()

        # Mock devices response
        devices_response = Mock()
        devices_response.json.return_value = {
            "success": True,
            "data": [
                {"id": "inactive_device", "connected": False, "type": 2},
                {"id": "active_device", "connected": True, "type": 2},
            ],
        }
        devices_response.raise_for_status.return_value = None
        devices_response.status_code = 200

        # Mock location response (optional call)
        location_response = Mock()
        location_response.status_code = 404

        mock_get.side_effect = [devices_response, location_response]

        devices = client.get_devices()

        active_devices = [d for d in devices if d.active]
        assert len(active_devices) == 1
        assert active_devices[0].id == "active_device"


class TestWaterTrackingDB:
    """Test database operations."""

    def test_init_creates_tables(self) -> None:
        """Test database initialization creates required tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db = WaterTrackingDB(tmp.name)

            # Check that tables exist
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name IN ('zones', 'watering_events', 'water_readings', 'zone_sessions')
                """
                )
                tables = [row[0] for row in cursor.fetchall()]

                assert "zones" in tables
                assert "watering_events" in tables
                assert "water_readings" in tables
                assert "zone_sessions" in tables

            os.unlink(tmp.name)

    def test_save_and_retrieve_zones(self) -> None:
        """Test saving and retrieving zones."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db = WaterTrackingDB(tmp.name)

            zones = [
                Zone(id="zone1", zone_number=1, name="Front Yard", enabled=True),
                Zone(id="zone2", zone_number=2, name="Back Yard", enabled=False),
            ]

            db.save_zones(zones)

            # Retrieve and verify
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM zones ORDER BY zone_number")
                rows = cursor.fetchall()

                assert len(rows) == 2
                assert rows[0]["name"] == "Front Yard"
                assert rows[0]["enabled"] == 1  # SQLite stores as integer
                assert rows[1]["name"] == "Back Yard"
                assert rows[1]["enabled"] == 0

            os.unlink(tmp.name)

    def test_compute_zone_sessions(self) -> None:
        """Test computing zone sessions from events."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db = WaterTrackingDB(tmp.name)

            # Create sample events
            start_time = datetime(2023, 1, 1, 10, 0)
            end_time = datetime(2023, 1, 1, 10, 30)

            events = [
                WateringEvent(
                    event_date=start_time,
                    zone_name="Front Yard",
                    zone_number=1,
                    event_type="ZONE_STARTED",
                ),
                WateringEvent(
                    event_date=end_time,
                    zone_name="Front Yard",
                    zone_number=1,
                    event_type="ZONE_COMPLETED",
                    duration_seconds=1800,
                ),
            ]

            db.save_watering_events(events)
            db.compute_zone_sessions()

            # Check computed sessions
            sessions = db.get_zone_sessions(datetime(2023, 1, 1), datetime(2023, 1, 2))

            assert len(sessions) == 1
            assert sessions[0]["zone_name"] == "Front Yard"
            assert sessions[0]["duration_seconds"] == 1800

            os.unlink(tmp.name)


class TestWeeklyReporter:
    """Test weekly reporting functionality."""

    def test_generate_weekly_report(self) -> None:
        """Test generating a weekly report."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db = WaterTrackingDB(tmp.name)
            reporter = WeeklyReporter(tmp.name)

            # Create sample data
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO zone_sessions 
                    (zone_name, zone_number, start_time, end_time, duration_seconds, total_water_used, average_flow_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "Front Yard",
                        1,
                        "2023-01-02 10:00:00",
                        "2023-01-02 10:30:00",
                        1800,
                        50.0,
                        1.67,
                    ),
                )
                conn.commit()

            # Generate report
            period_start = datetime(2023, 1, 2)  # Monday
            period_end = datetime(2023, 1, 9)  # Next Monday
            report = reporter.generate_period_report_with_dates(period_start, period_end)

            assert report.summary.total_watering_sessions == 1
            assert report.summary.total_duration_hours == 0.5
            assert report.summary.total_water_used_gallons == 50.0
            assert len(report.zones) == 1
            assert report.zones[0].zone_name == "Front Yard"

            os.unlink(tmp.name)


class TestWaterTrackingCollector:
    """Test the data collection service."""

    @patch("RachioFlume.collector.RachioClient")
    @patch("RachioFlume.collector.FlumeClient")
    def test_collector_initialization(self, mock_flume: Mock, mock_rachio: Mock) -> None:
        """Test collector initializes correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            collector = WaterTrackingCollector(tmp.name)

            assert collector.db is not None
            assert collector.poll_interval == 300  # Default 5 minutes

            os.unlink(tmp.name)

    @pytest.mark.asyncio
    @patch("RachioFlume.collector.RachioClient")
    @patch("RachioFlume.collector.FlumeClient")
    async def test_collect_once(self, mock_flume_class: Mock, mock_rachio_class: Mock) -> None:
        """Test single collection cycle."""
        # Setup mocks
        mock_rachio = Mock()
        mock_rachio.get_zones.return_value = [
            Zone(id="zone1", zone_number=1, name="Test Zone", enabled=True)
        ]
        mock_rachio.get_recent_events.return_value = []
        mock_rachio_class.return_value = mock_rachio

        mock_flume = Mock()
        mock_flume.get_usage.return_value = [WaterReading(timestamp=datetime.now(), value=1.0)]
        mock_flume_class.return_value = mock_flume

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            collector = WaterTrackingCollector(tmp.name)

            await collector.collect_once()

            # Verify methods were called
            mock_rachio.get_zones.assert_called_once()
            mock_flume.get_usage.assert_called()

            os.unlink(tmp.name)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
