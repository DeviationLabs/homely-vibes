#!/usr/bin/env python3

import pytest
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

from .august_client import AugustClient, AugustMonitor, LockState, LockStatus, DoorState


class TestLockState:
    def test_lock_state_creation(self):
        state = LockState(
            lock_id="test_lock_123",
            lock_name="Front Door",
            lock_status=LockStatus.LOCKED,
            timestamp=1640995200.0,
            battery_level=85.0,
            door_state=DoorState.CLOSED,
        )

        assert state.lock_id == "test_lock_123"
        assert state.lock_name == "Front Door"
        assert state.lock_status == LockStatus.LOCKED
        assert state.timestamp == 1640995200.0
        assert state.battery_level == 85.0
        assert state.door_state == DoorState.CLOSED

    def test_lock_state_serialization(self):
        state = LockState(
            lock_id="test_lock",
            lock_name="Test Lock",
            lock_status=LockStatus.LOCKED,
            timestamp=time.time(),
            battery_level=75.0,
        )

        state_dict = state.to_dict()
        assert isinstance(state_dict, dict)
        assert state_dict["lock_id"] == "test_lock"
        assert state_dict["lock_status"] == LockStatus.LOCKED

        restored_state = LockState.from_dict(state_dict)
        assert restored_state.lock_id == state.lock_id
        assert restored_state.lock_status == state.lock_status
        assert restored_state.battery_level == state.battery_level

    def test_lock_state_unknown_status(self):
        state = LockState(
            lock_id="test_lock_unknown",
            lock_name="Bluetooth Lock",
            lock_status=None,
            timestamp=time.time(),
            battery_level=60.0,
        )

        assert state.lock_id == "test_lock_unknown"
        assert state.lock_name == "Bluetooth Lock"
        assert state.lock_status is None
        assert state.battery_level == 60.0


class TestAugustClient:
    @pytest.fixture
    def client(self):
        return AugustClient("test@example.com", "password123", "+1234567890")

    @patch("August.august_client.aiohttp.ClientSession")
    @patch("August.august_client.ApiAsync")
    @patch("August.august_client.AuthenticatorAsync")
    @pytest.mark.anyio
    async def test_successful_authentication(
        self, mock_authenticator, mock_api, mock_session, client
    ):
        mock_auth_result = MagicMock()
        from yalexs.authenticator_async import AuthenticationState
        mock_auth_result.state = AuthenticationState.AUTHENTICATED
        mock_auth_result.access_token = "test_token_123"
        mock_authenticator.return_value.async_authenticate = AsyncMock(
            return_value=mock_auth_result
        )
        mock_authenticator.return_value.async_setup_authentication = AsyncMock()

        result = await client.authenticate()

        assert result is True
        assert client.access_token == "test_token_123"

    @patch("August.august_client.aiohttp.ClientSession")
    @patch("August.august_client.ApiAsync")
    @patch("August.august_client.AuthenticatorAsync")
    @pytest.mark.anyio
    async def test_failed_authentication(
        self, mock_authenticator, mock_api, mock_session, client
    ):
        mock_auth_result = MagicMock()
        from yalexs.authenticator_async import AuthenticationState
        mock_auth_result.state = AuthenticationState.BAD_PASSWORD
        mock_authenticator.return_value.async_authenticate = AsyncMock(
            return_value=mock_auth_result
        )
        mock_authenticator.return_value.async_setup_authentication = AsyncMock()

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
        assert isinstance(monitor.last_unlock_alerts, dict)
        assert isinstance(monitor.last_ajar_alerts, dict)
        assert isinstance(monitor.last_battery_alerts, dict)

    @pytest.mark.anyio
    async def test_monitor_check_locks_with_locked_status(self, monitor):
        """Test monitor handles locked status correctly."""
        with patch.object(monitor.client, 'get_all_lock_statuses') as mock_get_statuses:
            mock_lock_state = LockState(
                lock_id="test_lock",
                lock_name="Test Lock", 
                timestamp=time.time(),
                lock_status=LockStatus.LOCKED,
                battery_level=85.0,
                door_state=DoorState.CLOSED
            )
            mock_get_statuses.return_value = {"test_lock": mock_lock_state}
            
            await monitor.check_locks()
            
            # Should not track unlock time for locked doors
            assert "test_lock" not in monitor.unlock_start_times

    @pytest.mark.anyio
    async def test_monitor_check_locks_with_unknown_status(self, monitor):
        """Test monitor skips unknown lock status.""" 
        with patch.object(monitor.client, 'get_all_lock_statuses') as mock_get_statuses:
            mock_lock_state = LockState(
                lock_id="test_lock",
                lock_name="Test Lock",
                timestamp=time.time(), 
                lock_status=LockStatus.UNKNOWN,
                battery_level=85.0
            )
            mock_get_statuses.return_value = {"test_lock": mock_lock_state}
            
            await monitor.check_locks()
            
            # Should not track unlock time for unknown status
            assert "test_lock" not in monitor.unlock_start_times
