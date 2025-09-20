#!/usr/bin/env python3

import pytest
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

from august_client import AugustClient, AugustMonitor, LockState


class TestLockState:
    def test_lock_state_creation(self):
        state = LockState(
            lock_id="test_lock_123",
            lock_name="Front Door",
            is_locked=True,
            timestamp=1640995200.0,
            battery_level=85.0,
            door_state="CLOSED",
        )

        assert state.lock_id == "test_lock_123"
        assert state.lock_name == "Front Door"
        assert state.is_locked is True
        assert state.timestamp == 1640995200.0
        assert state.battery_level == 85.0
        assert state.door_state == "CLOSED"

    def test_lock_state_serialization(self):
        state = LockState(
            lock_id="test_lock",
            lock_name="Test Lock",
            is_locked=False,
            timestamp=time.time(),
            battery_level=75.0,
        )

        state_dict = state.to_dict()
        assert isinstance(state_dict, dict)
        assert state_dict["lock_id"] == "test_lock"
        assert state_dict["is_locked"] is False

        restored_state = LockState.from_dict(state_dict)
        assert restored_state.lock_id == state.lock_id
        assert restored_state.is_locked == state.is_locked
        assert restored_state.battery_level == state.battery_level

    def test_lock_state_unknown_status(self):
        state = LockState(
            lock_id="test_lock_unknown",
            lock_name="Bluetooth Lock",
            is_locked=None,
            timestamp=time.time(),
            battery_level=60.0,
        )

        assert state.lock_id == "test_lock_unknown"
        assert state.lock_name == "Bluetooth Lock"
        assert state.is_locked is None
        assert state.battery_level == 60.0


class TestAugustClient:
    @pytest.fixture
    def client(self):
        return AugustClient("test@example.com", "password123", "+1234567890")

    @patch("august_client.aiohttp.ClientSession")
    @patch("august_client.ApiAsync")
    @patch("august_client.AuthenticatorAsync")
    async def test_successful_authentication(
        self, mock_authenticator, mock_api, mock_session, client
    ):
        mock_auth_result = MagicMock()
        mock_auth_result.state = "AUTHENTICATED"
        mock_auth_result.access_token = "test_token_123"
        mock_authenticator.return_value.async_authenticate = AsyncMock(
            return_value=mock_auth_result
        )

        result = await client.authenticate()

        assert result is True
        assert client.access_token == "test_token_123"

    @patch("august_client.aiohttp.ClientSession")
    @patch("august_client.ApiAsync")
    @patch("august_client.AuthenticatorAsync")
    async def test_failed_authentication(
        self, mock_authenticator, mock_api, mock_session, client
    ):
        mock_auth_result = MagicMock()
        mock_auth_result.state = "BAD_PASSWORD"
        mock_authenticator.return_value.async_authenticate = AsyncMock(
            return_value=mock_auth_result
        )

        result = await client.authenticate()

        assert result is False
        assert client.access_token is None


class TestAugustMonitor:
    @pytest.fixture
    def temp_state_file(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            yield f.name

    @pytest.fixture
    def monitor(self, temp_state_file):
        monitor = AugustMonitor(
            "test@example.com", "password", unlock_threshold_minutes=5
        )
        monitor.state_file = temp_state_file
        return monitor

    def test_monitor_initialization(self, monitor):
        assert monitor.unlock_threshold == 5 * 60
        assert isinstance(monitor.unlock_start_times, dict)
        assert isinstance(monitor.last_alert_times, dict)
