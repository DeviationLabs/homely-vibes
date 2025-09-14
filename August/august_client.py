#!/usr/bin/env python3

import asyncio
import time
from typing import Optional, Dict, Any
import json
from dataclasses import dataclass, asdict
import aiohttp

try:
    from yalexs.api_async import ApiAsync
    from yalexs.authenticator_async import AuthenticatorAsync, AuthenticationState
    from yalexs.lock import Lock
except ImportError:
    print("yalexs library not found. Install with: uv add yalexs")
    raise

from lib import Constants
from lib.logger import get_logger
from lib.MyPushover import Pushover


@dataclass
class LockState:
    lock_id: str
    lock_name: str
    is_locked: bool
    timestamp: float
    battery_level: Optional[float] = None
    door_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LockState":
        return cls(**data)


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
        await self._ensure_session()
        if not self.access_token:
            if not await self.authenticate():
                return None

        try:
            assert self.api is not None
            assert self.access_token is not None
            lock_detail = await self.api.async_get_lock_detail(
                self.access_token, lock_id
            )
            lock_name = lock_detail.device_name

            # Handle lock status - only treat as unlocked if explicitly UNLOCKED
            lock_status_name = lock_detail.lock_status.name
            if lock_status_name == "LOCKED":
                is_locked = True
            elif lock_status_name == "UNLOCKED":
                is_locked = False
            else:
                # UNKNOWN or other status - don't treat as unlocked, skip monitoring
                self.logger.warning(
                    f"Lock {lock_name} has unknown status: {lock_status_name}"
                )
                return None

            battery_level = getattr(lock_detail, "battery_level", None)
            door_state = getattr(lock_detail, "door_state", None)

            lock_state = LockState(
                lock_id=lock_id,
                lock_name=lock_name,
                is_locked=is_locked,
                timestamp=time.time(),
                battery_level=battery_level,
                door_state=door_state.name if door_state else None,
            )

            self.logger.debug(
                f"Lock {lock_name} status: {'LOCKED' if is_locked else 'UNLOCKED'}"
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

    async def get_offline_locks(self) -> Dict[str, str]:
        """Get locks that are offline or have unknown status."""
        if not self.locks:
            await self.get_locks()

        offline_locks = {}
        for lock_id, lock in self.locks.items():
            status = await self.get_lock_status(lock_id)
            if status is None:  # Lock is offline/unknown
                offline_locks[lock_id] = lock.device_name

        return offline_locks


class AugustMonitor:
    def __init__(
        self,
        email: str,
        password: str,
        phone: Optional[str] = None,
        unlock_threshold_minutes: int = 5,
        door_ajar_threshold_minutes: int = 10,
        low_battery_threshold: int = 20,
    ):
        self.client = AugustClient(email, password, phone)
        self.unlock_threshold = unlock_threshold_minutes * 60
        self.door_ajar_threshold = door_ajar_threshold_minutes * 60
        self.low_battery_threshold = low_battery_threshold
        self.logger = get_logger(__name__)
        self.pushover = Pushover(
            Constants.PUSHOVER_USER, Constants.PUSHOVER_DEFAULT_TOKEN
        )
        # Tracking for different alert types
        self.unlock_start_times: Dict[str, float] = {}
        self.door_ajar_start_times: Dict[str, float] = {}
        self.last_alert_times: Dict[str, float] = {}
        self.last_battery_alerts: Dict[str, float] = {}
        self.last_lock_failure_alerts: Dict[str, float] = {}
        self.state_file = f"{Constants.LOGGING_DIR}/august_monitor_state.json"
        self._load_state()

    def _load_state(self) -> None:
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
                self.unlock_start_times = state.get("unlock_start_times", {})
                self.door_ajar_start_times = state.get("door_ajar_start_times", {})
                self.last_alert_times = state.get("last_alert_times", {})
                self.last_battery_alerts = state.get("last_battery_alerts", {})
                self.last_lock_failure_alerts = state.get(
                    "last_lock_failure_alerts", {}
                )
            self.logger.debug("Loaded monitor state from file")
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.debug("No existing state file found, starting fresh")

    def _save_state(self) -> None:
        try:
            state = {
                "unlock_start_times": self.unlock_start_times,
                "door_ajar_start_times": self.door_ajar_start_times,
                "last_alert_times": self.last_alert_times,
                "last_battery_alerts": self.last_battery_alerts,
                "last_lock_failure_alerts": self.last_lock_failure_alerts,
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

            existing_locks = set(statuses.keys())
            self.unlock_start_times = {
                k: v for k, v in self.unlock_start_times.items() if k in existing_locks
            }
            self.door_ajar_start_times = {
                k: v
                for k, v in self.door_ajar_start_times.items()
                if k in existing_locks
            }
            self.last_alert_times = {
                k: v for k, v in self.last_alert_times.items() if k in existing_locks
            }
            self.last_battery_alerts = {
                k: v for k, v in self.last_battery_alerts.items() if k in existing_locks
            }
            self.last_lock_failure_alerts = {
                k: v
                for k, v in self.last_lock_failure_alerts.items()
                if k in existing_locks
            }

            self._save_state()

        except Exception as e:
            self.logger.error(f"Error during lock check: {e}")

    async def _process_lock_status(
        self, lock_id: str, status: LockState, current_time: float
    ) -> None:
        # Check for unlock alerts
        if status.is_locked:
            if lock_id in self.unlock_start_times:
                unlock_duration = current_time - self.unlock_start_times[lock_id]
                self.logger.info(
                    f"Lock {status.lock_name} secured after "
                    f"{unlock_duration / 60:.1f} minutes"
                )
                del self.unlock_start_times[lock_id]
        else:
            if lock_id not in self.unlock_start_times:
                self.unlock_start_times[lock_id] = current_time
                self.logger.info(
                    f"Lock {status.lock_name} is unlocked - starting timer"
                )
            else:
                unlock_duration = current_time - self.unlock_start_times[lock_id]
                if unlock_duration >= self.unlock_threshold:
                    await self._send_unlock_alert(lock_id, status, unlock_duration)

        # Check for door ajar alerts (door open regardless of lock status)
        if status.door_state and status.door_state.upper() == "OPEN":
            if lock_id not in self.door_ajar_start_times:
                self.door_ajar_start_times[lock_id] = current_time
                self.logger.info(f"Door {status.lock_name} is ajar - starting timer")
            else:
                ajar_duration = current_time - self.door_ajar_start_times[lock_id]
                if ajar_duration >= self.door_ajar_threshold:
                    await self._send_door_ajar_alert(lock_id, status, ajar_duration)
        else:
            # Door is closed, clear ajar tracking
            if lock_id in self.door_ajar_start_times:
                ajar_duration = current_time - self.door_ajar_start_times[lock_id]
                self.logger.info(
                    f"Door {status.lock_name} closed after "
                    f"{ajar_duration / 60:.1f} minutes"
                )
                del self.door_ajar_start_times[lock_id]

        # Check for lock failure (door closed but not locked when it should be)
        if (
            status.door_state
            and status.door_state.upper() == "CLOSED"
            and not status.is_locked
        ):
            await self._check_lock_failure(lock_id, status, current_time)

    async def _send_unlock_alert(
        self, lock_id: str, status: LockState, unlock_duration: float
    ) -> None:
        current_time = time.time()

        last_alert = self.last_alert_times.get(lock_id, 0)
        alert_cooldown = 10 * 60  # 10 minutes between alerts

        if current_time - last_alert < alert_cooldown:
            return

        minutes_unlocked = unlock_duration / 60

        title = "🔓 August Lock Alert"
        message = (
            f"{status.lock_name} has been unlocked for {minutes_unlocked:.0f} minutes"
        )

        if status.battery_level:
            message += f"\nBattery: {status.battery_level}%"

        try:
            self.pushover.send_message(message, title=title)
            self.last_alert_times[lock_id] = current_time
            self.logger.warning(f"Sent unlock alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send pushover alert: {e}")

    async def _send_door_ajar_alert(
        self, lock_id: str, status: LockState, ajar_duration: float
    ) -> None:
        current_time = time.time()

        last_alert = self.last_alert_times.get(lock_id, 0)
        alert_cooldown = 10 * 60  # 10 minutes between alerts

        if current_time - last_alert < alert_cooldown:
            return

        minutes_ajar = ajar_duration / 60

        title = "🚪 August Door Alert"
        message = (
            f"{status.lock_name} door has been ajar for {minutes_ajar:.0f} minutes"
        )

        if status.battery_level:
            message += f"\nBattery: {status.battery_level}%"

        try:
            self.pushover.send_message(message, title=title)
            self.last_alert_times[lock_id] = current_time
            self.logger.warning(f"Sent door ajar alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send door ajar alert: {e}")

    async def _check_lock_failure(
        self, lock_id: str, status: LockState, current_time: float
    ) -> None:
        last_alert = self.last_lock_failure_alerts.get(lock_id, 0)
        alert_cooldown = 10 * 60  # 10 minutes between alerts

        if current_time - last_alert < alert_cooldown:
            return

        title = "🔐 August Lock Failure"
        message = f"{status.lock_name} door is closed but FAILED TO LOCK!"

        if status.battery_level:
            message += f"\nBattery: {status.battery_level}%"

        try:
            self.pushover.send_message(message, title=title)
            self.last_lock_failure_alerts[lock_id] = current_time
            self.logger.error(f"Sent lock failure alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send lock failure alert: {e}")

    async def _check_battery_level(
        self, lock_id: str, status: LockState, current_time: float
    ) -> None:
        if (
            not status.battery_level
            or status.battery_level >= self.low_battery_threshold
        ):
            return

        last_alert = self.last_battery_alerts.get(lock_id, 0)
        alert_cooldown = 24 * 60 * 60  # 24 hours between battery alerts

        if current_time - last_alert < alert_cooldown:
            return

        title = "🔋 August Low Battery"
        message = f"{status.lock_name} battery is low: {status.battery_level}%"

        try:
            self.pushover.send_message(message, title=title)
            self.last_battery_alerts[lock_id] = current_time
            self.logger.warning(f"Sent low battery alert: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send battery alert: {e}")

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
                    await asyncio.sleep(check_interval_seconds)
        finally:
            await self.client.close()

    async def get_status_report(self) -> str:
        try:
            statuses = await self.client.get_all_lock_statuses()
            offline_locks = await self.client.get_offline_locks()

            if not statuses and not offline_locks:
                return "No August locks found"

            lines = ["August Lock Status Report", "=" * 30]

            # Show online locks
            for status in statuses.values():
                if status is None:
                    continue
                lock_status = "🔒 LOCKED" if status.is_locked else "🔓 UNLOCKED"
                lines.append(f"{status.lock_name}: {lock_status}")

                if not status.is_locked and status.lock_id in self.unlock_start_times:
                    unlock_duration = (
                        time.time() - self.unlock_start_times[status.lock_id]
                    )
                    lines.append(f"  Unlocked for: {unlock_duration / 60:.1f} minutes")

                if status.lock_id in self.door_ajar_start_times:
                    ajar_duration = (
                        time.time() - self.door_ajar_start_times[status.lock_id]
                    )
                    lines.append(f"  Door ajar for: {ajar_duration / 60:.1f} minutes")

                if status.door_state:
                    lines.append(f"  Door: {status.door_state}")

                if status.battery_level:
                    battery_status = (
                        "LOW"
                        if status.battery_level < self.low_battery_threshold
                        else "OK"
                    )
                    lines.append(
                        f"  Battery: {status.battery_level}% ({battery_status})"
                    )

                lines.append("")

            # Show offline/unknown locks
            if offline_locks:
                lines.append("Offline/Unknown Status Locks:")
                for lock_name in offline_locks.values():
                    lines.append(f"{lock_name}: ⚠️ OFFLINE/UNKNOWN")
                    lines.append(
                        "  Status cannot be determined (check WiFi/bridge connection)"
                    )
                    lines.append("")

            return "\n".join(lines)

        except Exception as e:
            return f"Error getting status: {e}"
