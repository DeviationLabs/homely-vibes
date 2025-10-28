#!/usr/bin/env python3
"""Tests for August smart lock client module."""

import pytest
from typing import Any
from unittest.mock import Mock, patch, AsyncMock
from yalexs.lock import LockStatus, LockDoorStatus
from August.august_client import AugustClient, AugustMonitor, LockState


class TestLockState:
    """Test LockState dataclass"""

    def test_lock_state_creation(self) -> None:
        """Test creating a LockState object"""
        lock_state = LockState(
            lock_id="abc123",
            lock_name="Front Door",
            timestamp=1234567890.0,
            lock_status=LockStatus.LOCKED,
            battery_level=85.0,
            door_state=LockDoorStatus.CLOSED,
        )

        assert lock_state.lock_id == "abc123"
        assert lock_state.lock_name == "Front Door"
        assert lock_state.timestamp == 1234567890.0
        assert lock_state.lock_status == LockStatus.LOCKED
        assert lock_state.battery_level == 85.0
        assert lock_state.door_state == LockDoorStatus.CLOSED


class TestAugustClient:
    """Test AugustClient functionality"""

    @pytest.fixture
    def client(self) -> AugustClient:
        return AugustClient("test@example.com", "password123", "+1234567890")

    def test_init(self, client: AugustClient) -> None:
        """Test AugustClient initialization"""
        assert client.email == "test@example.com"
        assert client.password == "password123"
        assert client.phone == "+1234567890"
        assert client.session is None
        assert client.api is None
        assert client.authenticator is None
        assert client.access_token is None
        assert client.locks == {}

    @pytest.mark.asyncio
    async def test_ensure_session(self, client: AugustClient) -> None:
        """Test session initialization"""
        with (
            patch("August.august_client.aiohttp.ClientSession") as mock_session,
            patch("August.august_client.ApiAsync") as mock_api,
            patch("August.august_client.AuthenticatorAsync") as mock_auth,
            patch("August.august_client.Constants.LOGGING_DIR", "/tmp"),
        ):
            mock_session_instance = Mock()
            mock_session.return_value = mock_session_instance
            mock_auth_instance = AsyncMock()
            mock_auth.return_value = mock_auth_instance

            await client._ensure_session()

            assert client.session == mock_session_instance
            mock_api.assert_called_once_with(mock_session_instance)
            mock_auth.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_session(self, client: AugustClient) -> None:
        """Test closing client session"""
        mock_session = AsyncMock()
        client.session = mock_session

        await client.close()

        mock_session.close.assert_called_once()
        assert client.api is None
        assert client.authenticator is None
        assert client.session is None

    @pytest.mark.asyncio
    async def test_authenticate_success(self, client: AugustClient) -> None:
        """Test successful authentication"""
        mock_auth_result = Mock()
        mock_auth_result.state = "AUTHENTICATED"
        mock_auth_result.access_token = "token123"

        with (
            patch.object(client, "_ensure_session"),
            patch("August.august_client.AuthenticationState") as mock_auth_state,
        ):
            mock_auth_state.AUTHENTICATED = "AUTHENTICATED"
            client.authenticator = AsyncMock()
            client.authenticator.async_authenticate.return_value = mock_auth_result

            result = await client.authenticate()

            assert result is True
            assert client.access_token == "token123"

    @pytest.mark.asyncio
    async def test_authenticate_requires_validation(self, client: AugustClient) -> None:
        """Test authentication requiring 2FA"""
        mock_auth_result = Mock()
        mock_auth_result.state = "REQUIRES_VALIDATION"

        with (
            patch.object(client, "_ensure_session"),
            patch("August.august_client.AuthenticationState") as mock_auth_state,
        ):
            mock_auth_state.AUTHENTICATED = "AUTHENTICATED"
            mock_auth_state.REQUIRES_VALIDATION = "REQUIRES_VALIDATION"
            client.authenticator = AsyncMock()
            client.authenticator.async_authenticate.return_value = mock_auth_result

            result = await client.authenticate()

            assert result is False

    @pytest.mark.asyncio
    async def test_get_lock_status(self, client: AugustClient) -> None:
        """Test getting lock status"""
        mock_lock_detail = Mock()
        mock_lock_detail.device_name = "Front Door"
        mock_lock_detail.serial_number = "SN123456"
        mock_lock_detail.battery_level = 75.0
        mock_lock_detail.door_state = LockDoorStatus.CLOSED
        mock_lock_detail.lock_status = LockStatus.LOCKED

        with patch.object(client, "_ensure_session"):
            client.api = AsyncMock()
            client.access_token = "token123"
            client.api.async_get_lock_detail.return_value = mock_lock_detail

            result = await client.get_lock_status("lock123")

            assert result is not None
            assert result.lock_id == "lock123"
            assert result.lock_name == "Front Door"
            assert result.battery_level == 75.0
            assert result.door_state == LockDoorStatus.CLOSED
            assert result.lock_status == LockStatus.LOCKED

    @pytest.mark.asyncio
    async def test_get_all_lock_statuses(self, client: AugustClient) -> None:
        """Test getting all lock statuses"""
        mock_lock = Mock()
        mock_lock.device_id = "lock123"
        client.locks = {"lock123": mock_lock}

        with patch.object(client, "get_lock_status") as mock_get_status:
            mock_lock_state = LockState(
                lock_id="lock123",
                lock_name="Front Door",
                timestamp=1234567890.0,
                lock_status=LockStatus.LOCKED,
                battery_level=75.0,
                door_state=LockDoorStatus.CLOSED,
            )
            mock_get_status.return_value = mock_lock_state

            result = await client.get_all_lock_statuses()

            assert "lock123" in result
            assert result["lock123"] == mock_lock_state


class TestAugustMonitor:
    """Test AugustMonitor functionality"""

    @pytest.fixture
    def monitor(self) -> AugustMonitor:
        with (
            patch("August.august_client.AugustClient"),
            patch("August.august_client.Pushover"),
            patch("August.august_client.Constants.PUSHOVER_USER", "user123"),
            patch("August.august_client.Constants.PUSHOVER_TOKENS", {"August": "token123"}),
            patch("August.august_client.Constants.LOGGING_DIR", "/tmp"),
        ):
            return AugustMonitor("test@example.com", "password123")

    def test_init(self, monitor: AugustMonitor) -> None:
        """Test AugustMonitor initialization"""
        assert monitor.unlock_threshold == 5 * 60  # 5 minutes in seconds
        assert monitor.ajar_threshold == 10 * 60  # 10 minutes in seconds
        assert monitor.battery_threshold_pct == 20
        assert monitor.unlock_start_times == {}
        assert monitor.ajar_start_times == {}

    def test_load_state_no_file(self, monitor: AugustMonitor) -> None:
        """Test loading state when no file exists"""
        # State should initialize as empty dicts
        assert monitor.unlock_start_times == {}
        assert monitor.ajar_start_times == {}
        assert monitor.last_unlock_alerts == {}
        assert monitor.last_ajar_alerts == {}

    @patch("August.august_client.json.load")
    @patch("builtins.open")
    def test_load_state_with_file(self, mock_open: Any, mock_json_load: Any) -> None:
        """Test loading state from existing file"""
        mock_state = {
            "unlock_start_times": {"lock1": 1234567890.0},
            "ajar_start_times": {"lock2": 1234567900.0},
            "last_unlock_alerts": {"lock1": 1234567800.0},
            "last_ajar_alerts": {"lock2": 1234567850.0},
            "last_battery_alerts": {},
            "last_lock_failure_alerts": {},
        }
        mock_json_load.return_value = mock_state

        with (
            patch("August.august_client.AugustClient"),
            patch("August.august_client.Pushover"),
            patch("August.august_client.Constants.PUSHOVER_USER", "user123"),
            patch("August.august_client.Constants.PUSHOVER_TOKENS", {"August": "token123"}),
            patch("August.august_client.Constants.LOGGING_DIR", "/tmp"),
        ):
            monitor = AugustMonitor("test@example.com", "password123")

            # Verify the file was opened
            mock_open.assert_called_once()
            assert monitor.unlock_start_times == {"lock1": 1234567890.0}
            assert monitor.ajar_start_times == {"lock2": 1234567900.0}
            assert monitor.last_unlock_alerts == {"lock1": 1234567800.0}
            assert monitor.last_ajar_alerts == {"lock2": 1234567850.0}

    @pytest.mark.asyncio
    async def test_process_lock_status_locked(self, monitor: AugustMonitor) -> None:
        """Test processing lock status when lock becomes locked"""
        lock_state = LockState(
            lock_id="lock123",
            lock_name="Front Door",
            timestamp=1234567890.0,
            lock_status=LockStatus.LOCKED,
            battery_level=75.0,
            door_state=LockDoorStatus.CLOSED,
        )

        # Simulate lock was previously unlocked
        monitor.unlock_start_times["lock123"] = 1234567800.0  # 90 seconds ago

        with patch.object(monitor.pushover, "send_message") as mock_send:
            await monitor._process_lock_status("lock123", lock_state, 1234567890.0)

            # Should have removed from unlock_start_times and sent notification
            assert "lock123" not in monitor.unlock_start_times
            mock_send.assert_called_once()
            # Check the message contains expected content
            call_args = mock_send.call_args
            assert "Front Door" in call_args[0][0]
            assert "secured" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_process_lock_status_door_closed(self, monitor: AugustMonitor) -> None:
        """Test processing lock status when door becomes closed"""
        lock_state = LockState(
            lock_id="lock123",
            lock_name="Front Door",
            timestamp=1234567890.0,
            lock_status=LockStatus.LOCKED,
            battery_level=75.0,
            door_state=LockDoorStatus.CLOSED,
        )

        # Simulate door was previously ajar
        monitor.ajar_start_times["lock123"] = 1234567800.0  # 90 seconds ago

        with patch.object(monitor.pushover, "send_message") as mock_send:
            await monitor._process_lock_status("lock123", lock_state, 1234567890.0)

            # Should have removed from ajar_start_times and sent notification
            assert "lock123" not in monitor.ajar_start_times
            mock_send.assert_called_once()
            # Check the message contains expected content
            call_args = mock_send.call_args
            assert "Front Door" in call_args[0][0]
            assert "closed" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_check_battery_level_low(self, monitor: AugustMonitor) -> None:
        """Test battery level check with low battery"""
        lock_state = LockState(
            lock_id="lock123",
            lock_name="Front Door",
            timestamp=1234567890.0,
            lock_status=LockStatus.LOCKED,
            battery_level=15.0,  # Below threshold of 20%
            door_state=LockDoorStatus.CLOSED,
        )

        with patch.object(monitor.pushover, "send_message") as mock_send:
            await monitor._check_battery_level("lock123", lock_state, 1234567890.0)

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert "battery is low" in call_args[0][0].lower()
            assert "15.0%" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_check_battery_level_good(self, monitor: AugustMonitor) -> None:
        """Test battery level check with good battery"""
        lock_state = LockState(
            lock_id="lock123",
            lock_name="Front Door",
            timestamp=1234567890.0,
            lock_status=LockStatus.LOCKED,
            battery_level=85.0,  # Above threshold
            door_state=LockDoorStatus.CLOSED,
        )

        with patch.object(monitor.pushover, "send_message") as mock_send:
            await monitor._check_battery_level("lock123", lock_state, 1234567890.0)

            # Should not send notification for good battery
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_unknown_status_initial(self, monitor: AugustMonitor) -> None:
        """Test initial handling of unknown status."""
        status = LockState(
            lock_id="lock123",
            lock_name="Front Door",
            timestamp=1234567890.0,
            lock_status=LockStatus.UNKNOWN,
            battery_level=50.0,
            door_state=LockDoorStatus.CLOSED,
        )

        await monitor._handle_unknown_status("lock123", status, 1234567890.0)

        # Should start tracking unknown status
        assert "lock123" in monitor.unknown_status_start_times
        assert monitor.unknown_status_start_times["lock123"] == 1234567890.0
        assert monitor.unknown_recovery_attempted["lock123"] is False

    @pytest.mark.asyncio
    async def test_handle_unknown_status_recovery_sequence(self, monitor: AugustMonitor) -> None:
        """Test unknown status recovery after 30+ minutes."""
        lock_id = "lock123"
        start_time = 1234567890.0
        current_time = start_time + (31 * 60)  # 31 minutes later

        # Pre-populate unknown status start time
        monitor.unknown_status_start_times[lock_id] = start_time
        monitor.unknown_recovery_attempted[lock_id] = False

        status = LockState(
            lock_id=lock_id,
            lock_name="Front Door",
            timestamp=current_time,
            lock_status=LockStatus.UNKNOWN,
            battery_level=50.0,
            door_state=LockDoorStatus.CLOSED,
        )

        with (
            patch.object(
                monitor.client, "unlock_lock", new=AsyncMock(return_value=True)
            ) as mock_unlock,
            patch.object(
                monitor.client, "lock_lock", new=AsyncMock(return_value=True)
            ) as mock_lock,
            patch.object(monitor.pushover, "send_message") as mock_pushover,
            patch("asyncio.sleep"),
        ):
            await monitor._handle_unknown_status(lock_id, status, current_time)

            # Should attempt recovery sequence
            mock_unlock.assert_called_once_with(lock_id)
            mock_lock.assert_called_once_with(lock_id)
            mock_pushover.assert_called_once()
            assert monitor.unknown_recovery_attempted[lock_id] is True

    @pytest.mark.asyncio
    async def test_handle_unknown_status_resolved_after_recovery(
        self, monitor: AugustMonitor
    ) -> None:
        """Test state reset after status resolves following recovery attempt."""
        lock_id = "lock123"
        start_time = 1234567890.0
        current_time = start_time + (35 * 60)  # 35 minutes later

        # Pre-populate state as if recovery was attempted
        monitor.unknown_status_start_times[lock_id] = start_time
        monitor.unknown_recovery_attempted[lock_id] = True

        # Status is now resolved as LOCKED
        status = LockState(
            lock_id=lock_id,
            lock_name="Front Door",
            timestamp=current_time,
            lock_status=LockStatus.LOCKED,  # Now resolved
            battery_level=50.0,
            door_state=LockDoorStatus.CLOSED,
        )

        await monitor._handle_unknown_status(lock_id, status, current_time)

        # Should reset state since status resolved after recovery
        assert lock_id not in monitor.unknown_status_start_times
        assert lock_id not in monitor.unknown_recovery_attempted

    @pytest.mark.asyncio
    async def test_handle_unknown_status_resolved_no_recovery(self, monitor: AugustMonitor) -> None:
        """Test state reset when status resolves before recovery attempt."""
        lock_id = "lock123"
        start_time = 1234567890.0
        current_time = start_time + (10 * 60)  # 10 minutes later (< 30 min threshold)

        # Pre-populate state as unknown but no recovery attempted yet
        monitor.unknown_status_start_times[lock_id] = start_time
        monitor.unknown_recovery_attempted[lock_id] = False

        # Status is now resolved
        status = LockState(
            lock_id=lock_id,
            lock_name="Front Door",
            timestamp=current_time,
            lock_status=LockStatus.LOCKED,  # Now resolved
            battery_level=50.0,
            door_state=LockDoorStatus.CLOSED,
        )

        await monitor._handle_unknown_status(lock_id, status, current_time)

        # Should clear tracking since resolved before recovery
        assert lock_id not in monitor.unknown_status_start_times
        assert lock_id not in monitor.unknown_recovery_attempted

    @pytest.mark.asyncio
    async def test_handle_unknown_status_no_duplicate_recovery(
        self, monitor: AugustMonitor
    ) -> None:
        """Test that recovery is only attempted once."""
        lock_id = "lock123"
        start_time = 1234567890.0
        current_time = start_time + (35 * 60)  # 35 minutes later

        # Pre-populate state as if recovery was already attempted
        monitor.unknown_status_start_times[lock_id] = start_time
        monitor.unknown_recovery_attempted[lock_id] = True  # Already attempted

        status = LockState(
            lock_id=lock_id,
            lock_name="Front Door",
            timestamp=current_time,
            lock_status=LockStatus.UNKNOWN,  # Still unknown
            battery_level=50.0,
            door_state=LockDoorStatus.CLOSED,
        )

        with (
            patch.object(monitor.client, "unlock_lock", new=AsyncMock()) as mock_unlock,
            patch.object(monitor.client, "lock_lock", new=AsyncMock()) as mock_lock,
            patch.object(monitor.pushover, "send_message") as mock_pushover,
        ):
            await monitor._handle_unknown_status(lock_id, status, current_time)

            # Should NOT attempt recovery again
            mock_unlock.assert_not_called()
            mock_lock.assert_not_called()
            mock_pushover.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
