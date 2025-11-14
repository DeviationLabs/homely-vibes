#!/usr/bin/env python3

import asyncio
import time
from typing import Optional, Dict
import json
from dataclasses import dataclass
import aiohttp
from datetime import datetime

from yalexs.api_async import ApiAsync
from yalexs.authenticator_async import AuthenticatorAsync, AuthenticationState
from yalexs.lock import Lock, LockStatus, LockDoorStatus

from lib import Constants
from lib.logger import get_logger
from lib.MyPushover import Pushover


@dataclass
class LockState:
    lock_id: str
    lock_name: str
    timestamp: float
    lock_status: LockStatus
    battery_level: float
    door_state: LockDoorStatus


class AugustClient:
    def __init__(self, email: str, password: str, phone: Optional[str] = None):
        self.email = email
        self.password = password
        self.phone = phone
        self.logger = get_logger(__name__)
        self.session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[ApiAsync] = None
        self.authenticator: Optional[AuthenticatorAsync] = None
        self.access_token: Optional[str] = None
        self.locks: Dict[str, Lock] = {}

    async def unlock_lock(self, lock_id: str) -> bool:
        """Unlock a specific lock."""
        try:
            assert self.api is not None
            assert self.access_token is not None
            result = await self.api.async_unlock(self.access_token, lock_id)
            self.logger.info(f"Unlock command sent for lock {lock_id}, result: {result}")
            return True
        except Exception as e:
            self.logger.error(f"Error unlocking lock {lock_id}: {e}")
            return False

    async def lock_lock(self, lock_id: str) -> bool:
        """Lock a specific lock."""
        try:
            assert self.api is not None
            assert self.access_token is not None
            result = await self.api.async_lock(self.access_token, lock_id)
            self.logger.info(f"Lock command sent for lock {lock_id}, result: {result}")
            return True
        except Exception as e:
            self.logger.error(f"Error locking lock {lock_id}: {e}")
            return False

    async def _ensure_session(self) -> None:
        """Ensure aiohttp session and API are initialized."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            self.api = ApiAsync(self.session)
            # Use token caching to persist authentication across restarts
            cache_file = f"{Constants.LOGGING_DIR}/august_auth_token.json"
            self.authenticator = AuthenticatorAsync(
                self.api,
                "email",
                self.email,
                self.password,
                access_token_cache_file=cache_file,
            )
            # Setup authentication - this initializes the _authentication property
            await self.authenticator.async_setup_authentication()

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None
            self.api = None
            self.authenticator = None

    async def authenticate(self) -> bool:
        await self._ensure_session()
        try:
            assert self.authenticator is not None
            self.logger.debug("Attempting August authentication...")
            auth_result = await self.authenticator.async_authenticate()

            if auth_result is None:
                self.logger.error("Authentication returned None - check credentials")
                return False

            self.logger.debug(f"Authentication result state: {auth_result.state}")

            if auth_result.state == AuthenticationState.AUTHENTICATED:
                self.access_token = auth_result.access_token
                self.logger.info("Successfully authenticated with August API")
                return True
            elif auth_result.state == AuthenticationState.REQUIRES_VALIDATION:
                self.logger.error("August authentication requires 2FA validation")
                self.logger.error("Please complete 2FA in the August app and try again")
                return False
            else:
                self.logger.error(f"August authentication failed: {auth_result.state}")
                return False

        except Exception as e:
            self.logger.error(f"Error during August authentication: {e}")
            self.logger.error(
                "Make sure AUGUST_EMAIL and AUGUST_PASSWORD are correct in Constants.py"
            )
            return False

    async def get_locks(self) -> Dict[str, Lock]:
        await self._ensure_session()
        if not self.access_token:
            if not await self.authenticate():
                raise RuntimeError("Failed to authenticate with August API")

        try:
            assert self.api is not None
            assert self.access_token is not None
            locks = await self.api.async_get_locks(self.access_token)
            self.locks = {lock.device_id: lock for lock in locks}
            self.logger.info(f"Found {len(self.locks)} August locks")
            return self.locks
        except Exception as e:
            self.logger.error(f"Error retrieving locks: {e}")
            raise

    async def get_lock_status(self, lock_id: str) -> Optional[LockState]:
        try:
            assert self.api is not None
            assert self.access_token is not None
            lock_detail = await self.api.async_get_lock_detail(self.access_token, lock_id)
            lock_name = lock_detail.device_name
            lock_serial = lock_detail.serial_number

            battery_level = getattr(lock_detail, "battery_level", -1)
            door_state = getattr(lock_detail, "door_state", LockDoorStatus.UNKNOWN)
            lock_status = getattr(lock_detail, "lock_status", LockStatus.UNKNOWN)

            self.logger.info(
                f"Lock {lock_name} ({lock_serial}) lock_status: {lock_status} door_state: {door_state} battery_level: {battery_level}"
            )

            if door_state == LockDoorStatus.UNKNOWN or lock_status == LockStatus.UNKNOWN:
                self.logger.warning(
                    f"Lock {lock_name} has UNKNOWNs in state. Please debug."
                    f"Raw LockStatus data: {lock_detail}"
                )

            lock_state = LockState(
                lock_id=lock_id,
                lock_name=lock_name,
                timestamp=time.time(),
                lock_status=lock_detail.lock_status,
                battery_level=battery_level,
                door_state=door_state,
            )
            return lock_state

        except Exception as e:
            self.logger.error(f"Error getting lock status for {lock_id}: {e}")
            return None

    async def get_all_lock_statuses(self) -> Dict[str, LockState]:
        if not self.locks:
            await self.get_locks()

        statuses = {}
        for lock_id in self.locks.keys():
            status = await self.get_lock_status(lock_id)
            if status:
                statuses[lock_id] = status

        return statuses


class AugustMonitor:
    def __init__(
        self,
        email: str,
        password: str,
        phone: Optional[str] = None,
        unlock_threshold_minutes: int = 5,
        ajar_threshold_minutes: int = 10,
        battery_threshold_pct: int = 20,
        battery_alert_cooldown_minutes: int = 42 * 60,  # 1.75 days
        door_alert_cooldown_minutes: int = 2,
    ):
        self.client = AugustClient(email, password, phone)
        self.unlock_threshold = unlock_threshold_minutes * 60
        self.ajar_threshold = ajar_threshold_minutes * 60
        self.battery_threshold_pct = battery_threshold_pct
        self.battery_alert_cooldown = battery_alert_cooldown_minutes * 60
        self.door_alert_cooldown = door_alert_cooldown_minutes * 60
        self.logger = get_logger(__name__)
        self.pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["August"])
        self.unlock_start_times: Dict[str, float] = {}
        self.ajar_start_times: Dict[str, float] = {}
        self.last_unlock_alerts: Dict[str, float] = {}
        self.last_ajar_alerts: Dict[str, float] = {}
        self.last_battery_alerts: Dict[str, float] = {}
        self.last_lock_failure_alerts: Dict[str, float] = {}
        # Track unknown status for recovery
        self.unknown_status_start_times: Dict[str, float] = {}
        self.unknown_recovery_attempted: Dict[str, bool] = {}
        self.unknown_threshold = 60 * 60  # 60 minutes
        self.state_file = f"{Constants.LOGGING_DIR}/august_monitor_state.json"
        self._load_state()

    def _load_state(self) -> None:
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
                self.unlock_start_times = state.get("unlock_start_times", {})
                self.ajar_start_times = state.get("ajar_start_times", {})
                self.last_unlock_alerts = state.get("last_unlock_alerts", {})
                self.last_ajar_alerts = state.get("last_ajar_alerts", {})
                self.last_battery_alerts = state.get("last_battery_alerts", {})
                self.last_lock_failure_alerts = state.get("last_lock_failure_alerts", {})
                self.unknown_status_start_times = state.get("unknown_status_start_times", {})
                self.unknown_recovery_attempted = state.get("unknown_recovery_attempted", {})
            self.logger.debug("Loaded monitor state from file")
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.debug("No existing state file found, starting fresh")

    def _save_state(self) -> None:
        try:
            state = {
                "unlock_start_times": self.unlock_start_times,
                "ajar_start_times": self.ajar_start_times,
                "last_unlock_alerts": self.last_unlock_alerts,
                "last_ajar_alerts": self.last_ajar_alerts,
                "last_battery_alerts": self.last_battery_alerts,
                "last_lock_failure_alerts": self.last_lock_failure_alerts,
                "unknown_status_start_times": self.unknown_status_start_times,
                "unknown_recovery_attempted": self.unknown_recovery_attempted,
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f)
            self.logger.debug("Saved monitor state to file")
        except Exception as e:
            self.logger.error(f"Error saving state: {e}")

    async def check_locks(self) -> None:
        try:
            statuses = await self.client.get_all_lock_statuses()

            current_time = time.time()

            for lock_id, status in statuses.items():
                await self._process_lock_status(lock_id, status, current_time)
                await self._check_battery_level(lock_id, status, current_time)
                await self._handle_unknown_status(lock_id, status, current_time)

            existing_locks = set(statuses.keys())
            self.unlock_start_times = {
                k: v for k, v in self.unlock_start_times.items() if k in existing_locks
            }
            self.ajar_start_times = {
                k: v for k, v in self.ajar_start_times.items() if k in existing_locks
            }
            self.last_unlock_alerts = {
                k: v for k, v in self.last_unlock_alerts.items() if k in existing_locks
            }
            self.last_ajar_alerts = {
                k: v for k, v in self.last_ajar_alerts.items() if k in existing_locks
            }
            self.last_battery_alerts = {
                k: v for k, v in self.last_battery_alerts.items() if k in existing_locks
            }
            self.last_lock_failure_alerts = {
                k: v for k, v in self.last_lock_failure_alerts.items() if k in existing_locks
            }
            self.unknown_status_start_times = {
                k: v for k, v in self.unknown_status_start_times.items() if k in existing_locks
            }
            self.unknown_recovery_attempted = {
                k: v for k, v in self.unknown_recovery_attempted.items() if k in existing_locks
            }

            self._save_state()

        except Exception as e:
            self.logger.error(f"Error during lock check: {e}")

    async def _process_lock_status(
        self, lock_id: str, status: LockState, current_time: float
    ) -> None:
        if status.lock_status == LockStatus.LOCKED:
            if lock_id in self.unlock_start_times:
                unlock_duration = current_time - self.unlock_start_times[lock_id]
                message = (
                    f"Lock {status.lock_name} secured after {unlock_duration / 60:.1f} minutes"
                )
                self.logger.info(message)

                self.pushover.send_message(
                    message,
                    title="August Lock Secured",
                    priority=0,
                )

                del self.unlock_start_times[lock_id]
        else:
            if lock_id not in self.unlock_start_times:
                self.unlock_start_times[lock_id] = current_time
                self.logger.info(f"Lock {status.lock_name} is unlocked - starting timer")
            else:
                unlock_duration = current_time - self.unlock_start_times[lock_id]
                if unlock_duration >= self.unlock_threshold:
                    last_alert = self.last_unlock_alerts.get(lock_id, 0)
                    if current_time - last_alert >= self.door_alert_cooldown:
                        await self._send_unlock_alert(lock_id, status, unlock_duration)
                        self.last_unlock_alerts[lock_id] = current_time

        if status.door_state == LockDoorStatus.CLOSED:
            if lock_id in self.ajar_start_times:
                ajar_duration = current_time - self.ajar_start_times[lock_id]
                message = f"Door {status.lock_name} closed after {ajar_duration / 60:.1f} minutes"
                self.logger.info(message)
                self.pushover.send_message(message, title="August Door Closed", priority=0)

                del self.ajar_start_times[lock_id]
        else:
            if lock_id not in self.ajar_start_times:
                self.ajar_start_times[lock_id] = current_time
                self.logger.info(f"Door {status.lock_name} is ajar - starting timer")
            else:
                ajar_duration = current_time - self.ajar_start_times[lock_id]
                if ajar_duration >= self.ajar_threshold:
                    last_alert = self.last_ajar_alerts.get(lock_id, 0)
                    if current_time - last_alert >= self.door_alert_cooldown:
                        await self._send_door_ajar_alert(lock_id, status, ajar_duration)
                        self.last_ajar_alerts[lock_id] = current_time

    async def _send_unlock_alert(
        self, lock_id: str, status: LockState, unlock_duration: float
    ) -> None:
        minutes_unlocked = unlock_duration / 60

        title = "🔓 August Lock Alert"
        message = f"{status.lock_name} has been unlocked for {minutes_unlocked:.0f} minutes"

        try:
            self.pushover.send_message(message, title=title, priority=1)
            self.logger.warning(f"Sent unlock alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send pushover alert: {e}")

    async def _send_door_ajar_alert(
        self, lock_id: str, status: LockState, ajar_duration: float
    ) -> None:
        minutes_ajar = ajar_duration / 60

        title = "🚪 August Door Alert"
        message = f"{status.lock_name} door has been ajar for {minutes_ajar:.0f} minutes"

        try:
            self.pushover.send_message(message, title=title, priority=1)
            self.logger.warning(f"Sent door ajar alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send door ajar alert: {e}")

    async def _check_battery_level(
        self, lock_id: str, status: LockState, current_time: float
    ) -> None:
        if not status.battery_level or status.battery_level >= self.battery_threshold_pct:
            return

        last_alert = self.last_battery_alerts.get(lock_id, 0)
        if current_time - last_alert < self.battery_alert_cooldown:
            self.logger.info(
                f"Skipping battery alert for {status.lock_name} (cooldown) last_alert: {datetime.fromtimestamp(last_alert)}"
            )
            return

        title = "🔋 August Low Battery"
        message = f"{status.lock_name} battery is low: {status.battery_level}%"

        try:
            self.pushover.send_message(message, title=title, priority=2)
            self.last_battery_alerts[lock_id] = current_time
            self.logger.warning(f"Sent low battery alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send battery alert: {e}")

    async def _handle_unknown_status(
        self, lock_id: str, status: LockState, current_time: float
    ) -> None:
        """Handle unknown lock status with recovery mechanism."""
        if status.lock_status == LockStatus.UNKNOWN:
            # Start tracking unknown status if not already tracked
            if lock_id not in self.unknown_status_start_times:
                self.unknown_status_start_times[lock_id] = current_time
                self.logger.warning(f"Lock {status.lock_name} status is UNKNOWN - starting timer")
            else:
                unknown_duration = current_time - self.unknown_status_start_times[lock_id]

                # If unknown for > 30 minutes and recovery not yet attempted
                if (
                    unknown_duration >= self.unknown_threshold
                ):
                    self.logger.warning(
                        f"Lock {status.lock_name} has been UNKNOWN for {unknown_duration / 60:.1f} minutes. "
                        f"Attempting unlock/lock recovery sequence."
                    )

                    # Attempt unlock then lock sequence
#                    unlock_success = await self.client.unlock_lock(lock_id)
                    unlock_success = True # just lock without an unlock attempt
                    if unlock_success:
                        lock_success = await self.client.lock_lock(lock_id)
                        if lock_success:
                            self.logger.info(
                                f"Successfully sent lock command for {status.lock_name}"
                            )
                            # Send notification about recovery attempt
                            try:
                                message = (
                                    f"Attempted recovery for {status.lock_name} "
                                    f"(unknown status for {unknown_duration / 60:.1f} min). "
                                    f"Sent unlock/lock sequence."
                                )
                                self.pushover.send_message(
                                    message, title="🔧 August Lock Recovery", priority=1
                                )
                            except Exception as e:
                                self.logger.error(f"Failed to send recovery notification: {e}")
                        else:
                            self.logger.error(f"Failed to send lock command for {status.lock_name}")
                    else:
                        self.logger.error(f"Failed to send unlock command for {status.lock_name}")
        else:
            # Clear unknown tracking
            self.unknown_status_start_times.pop(lock_id, None)

    async def run_continuous_monitoring(self, check_interval_seconds: int = 60) -> None:
        self.logger.info(
            f"Starting continuous August lock monitoring "
            f"(check every {check_interval_seconds}s, "
            f"alert after {self.unlock_threshold / 60:.0f}min)"
        )

        try:
            while True:
                try:
                    await self.check_locks()
                    await asyncio.sleep(check_interval_seconds)
                except KeyboardInterrupt:
                    self.logger.info("Monitoring stopped by user")
                    break
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
        finally:
            await self.client.close()
