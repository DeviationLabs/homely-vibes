"""Tests for the Rachio-Flume water tracking integration."""

import pytest
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch
import os

from rachio_client import RachioClient, Zone, WateringEvent
from flume_client import FlumeClient, WaterReading
from data_storage import WaterTrackingDB
from collector import WaterTrackingCollector
from reporter import WeeklyReporter


class TestRachioClient:
    """Test Rachio API client."""

    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        with patch.dict(
            os.environ, {"RACHIO_API_KEY": "test_key", "RACHIO_ID": "test_device"}
        ):
            client = RachioClient()
            assert client.api_key == "test_key"
            assert client.device_id == "test_device"

    def test_init_missing_credentials(self):
        """Test initialization fails without credentials."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Rachio API key required"):
                RachioClient()

    @patch("rachio_client.requests.get")
    def test_get_zones(self, mock_get):
        """Test getting zones from device."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "zones": [
                {"id": "zone1", "zoneNumber": 1, "name": "Front Yard", "enabled": True},
                {"id": "zone2", "zoneNumber": 2, "name": "Back Yard", "enabled": False},
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch.dict(
            os.environ, {"RACHIO_API_KEY": "test_key", "RACHIO_ID": "test_device"}
        ):
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

    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        with patch.dict(
            os.environ,
            {
                "FLUME_CLIENT_ID": "client123",
                "FLUME_CLIENT_SECRET": "secret456",
                "FLUME_USER_EMAIL": "test@example.com",
                "FLUME_PASSWORD": "password789",
            },
        ):
            with patch.object(
                FlumeClient, "_get_access_token", return_value="token123"
            ):
                client = FlumeClient()
                assert client.client_id == "client123"
                assert client.client_secret == "secret456"
                assert client.username == "test@example.com"
                assert client.password == "password789"

    def test_init_missing_credentials(self):
        """Test initialization fails without credentials."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(Exception):  # Will fail on missing OAuth credentials
                FlumeClient()

    @patch("flume_client.requests.get")
    @patch("flume_client.requests.post")
    def test_get_usage(self, mock_post, mock_get):
        """Test getting water usage data."""
        # Mock device list response
        mock_devices_response = Mock()
        mock_devices_response.json.return_value = [
            {"id": "device456", "name": "Water Meter", "active": True}
        ]
        mock_devices_response.raise_for_status.return_value = None
        mock_get.return_value = mock_devices_response

        # Mock usage data response
        mock_usage_response = Mock()
        mock_usage_response.json.return_value = {
            "data": [
                {
                    "data": [
                        {"datetime": "2023-01-01T10:00:00Z", "value": 1.5},
                        {"datetime": "2023-01-01T10:01:00Z", "value": 2.0},
                    ]
                }
            ]
        }
        mock_usage_response.raise_for_status.return_value = None
        mock_post.return_value = mock_usage_response

        with patch.dict(
            os.environ,
            {
                "FLUME_ACCESS_TOKEN": "token789",
            },
        ):
            client = FlumeClient()
            start_time = datetime(2023, 1, 1, 10, 0)
            end_time = datetime(2023, 1, 1, 10, 2)

            readings = client.get_usage(start_time, end_time)

            assert len(readings) == 2
            assert readings[0].value == 1.5
            assert readings[1].value == 2.0

    @patch("flume_client.requests.get")
    def test_get_devices(self, mock_get):
        """Test getting user devices."""
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": "device1", "name": "Main Meter", "active": True},
            {
                "id": "device2",
                "name": "Pool Meter",
                "active": False,
                "location": "Pool",
            },
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"FLUME_ACCESS_TOKEN": "token789"}):
            client = FlumeClient()
            devices = client.get_devices()

            assert len(devices) == 2
            assert devices[0].id == "device1"
            assert devices[0].name == "Main Meter"
            assert devices[0].active is True
            assert devices[1].id == "device2"
            assert devices[1].name == "Pool Meter"
            assert devices[1].active is False
            assert devices[1].location == "Pool"

    @patch("flume_client.requests.get")
    def test_get_device_id_auto_selection(self, mock_get):
        """Test automatic device ID selection."""
        mock_response = Mock()
        mock_response.json.return_value = [
            {"id": "inactive_device", "name": "Old Meter", "active": False},
            {"id": "active_device", "name": "Current Meter", "active": True},
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"FLUME_ACCESS_TOKEN": "token789"}):
            client = FlumeClient()
            device_id = client.get_device_id()

            assert device_id == "active_device"


class TestWaterTrackingDB:
    """Test database operations."""

    def test_init_creates_tables(self):
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

    def test_save_and_retrieve_zones(self):
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

    def test_compute_zone_sessions(self):
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

    def test_generate_weekly_report(self):
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
            week_start = datetime(2023, 1, 2)  # Monday
            report = reporter.generate_weekly_report(week_start)

            assert report["summary"]["total_watering_sessions"] == 1
            assert report["summary"]["total_duration_hours"] == 0.5
            assert report["summary"]["total_water_used_gallons"] == 50.0
            assert len(report["zones"]) == 1
            assert report["zones"][0]["zone_name"] == "Front Yard"

            os.unlink(tmp.name)


class TestWaterTrackingCollector:
    """Test the data collection service."""

    @patch("collector.RachioClient")
    @patch("collector.FlumeClient")
    def test_collector_initialization(self, mock_flume, mock_rachio):
        """Test collector initializes correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            collector = WaterTrackingCollector(tmp.name)

            assert collector.db is not None
            assert collector.poll_interval == 300  # Default 5 minutes

            os.unlink(tmp.name)

    @patch("collector.RachioClient")
    @patch("collector.FlumeClient")
    async def test_collect_once(self, mock_flume_class, mock_rachio_class):
        """Test single collection cycle."""
        # Setup mocks
        mock_rachio = Mock()
        mock_rachio.get_zones.return_value = [
            Zone(id="zone1", zone_number=1, name="Test Zone", enabled=True)
        ]
        mock_rachio.get_recent_events.return_value = []
        mock_rachio_class.return_value = mock_rachio

        mock_flume = Mock()
        mock_flume.get_usage.return_value = [
            WaterReading(timestamp=datetime.now(), value=1.0)
        ]
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
