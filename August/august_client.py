#!/usr/bin/env python3

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional
import json
from dataclasses import dataclass
import aiohttp
from datetime import datetime

from yalexs.api_async import ApiAsync
from yalexs.authenticator_async import AuthenticatorAsync, AuthenticationState
from yalexs.authenticator_common import Authentication
from yalexs.lock import Lock, LockStatus, LockDoorStatus

from lib.config import get_config
from lib.logger import get_logger
from lib.MyPushover import Pushover
from lib.notifications import Notifier
from lib.secure_io import ensure_secret_perms

# August revoked the API key yalexs ships for Brand.AUGUST (d9984f29...): the
# session/password-auth endpoint returns 403 {"code":"Forbidden","message":
# "API key is not valid"}. The legacy key yalexs also ships (7cab4bbd...) still
# works. We override the global BrandConfig so AuthenticatorAsync/ApiAsync send
# the working key. Only override when the current key is the known-revoked
# value so a future yalexs fix is not clobbered.
_REVOKED_AUGUST_API_KEY = "d9984f29-07a6-816e-e1c9-44ec9d1be431"
_WORKING_AUGUST_API_KEY = "7cab4bbd-2693-4fc1-b99b-dec0fb20f9d4"


def apply_working_api_key(logger: Optional[logging.Logger] = None) -> bool:
    """Fall back to the legacy August API key if yalexs's current key is revoked.

    Mutates the yalexs global BRAND_CONFIG[Brand.AUGUST].api_key in place so
    that AuthenticatorAsync/ApiAsync send a key August still accepts. Returns
    True if a fallback was applied, False if the shipped key is not the known
    revoked value (e.g. yalexs shipped a fix).
    """
    from yalexs.const import BRAND_CONFIG, Brand

    brand_config = BRAND_CONFIG[Brand.AUGUST]
    if brand_config.api_key != _REVOKED_AUGUST_API_KEY:
        return False
    brand_config.api_key = _WORKING_AUGUST_API_KEY
    if logger is not None:
        logger.warning(
            "August revoked yalexs API key %s; falling back to legacy key %s.",
            _REVOKED_AUGUST_API_KEY,
            _WORKING_AUGUST_API_KEY,
        )
    return True


def load_cached_install_id(cache_file: str) -> Optional[str]:
    """Return the install_id persisted in the August token cache, if any.

    yalexs discards the cached install_id when the access token expires
    (authenticator_async._read_access_token_file resets to self._install_id,
    which is the constructor arg, not the cached value). That makes August see
    a fresh device on every re-auth after expiry and forces 2FA. We feed the
    cached install_id back through the AuthenticatorAsync constructor so the
    validated device identity survives token expiry.
    """
    try:
        with open(cache_file, "r") as f:
            data: dict[str, Any] = json.load(f)
        install_id = data.get("install_id")
        return install_id if isinstance(install_id, str) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@dataclass
class LockState:
    lock_id: str
    lock_name: str
    timestamp: float
    lock_status: LockStatus
    battery_level: float
    door_state: LockDoorStatus


class AugustClient:
    def __init__(
        self,
        email: str,
        password: str,
        phone: Optional[str] = None,
        *,
        pushover: Optional[Notifier] = None,
    ):
        self.email = email
        self.password = password
        self.phone = phone
        self.logger = get_logger(__name__)
        self.session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[ApiAsync] = None
        self.api_auth: Optional[ApiAsync] = None
        self.authenticator: Optional[AuthenticatorAsync] = None
        self.access_token: Optional[str] = None
        self.locks: Dict[str, Lock] = {}
        # Injectable Pushover so tests can pass a recording double instead of
        # touching real config + production tokens. Matches the RingSecurity /
        # RingBeams factory-injection pattern; see CLAUDE.md "NEVER use patch()".
        if pushover is None:
            cfg = get_config()
            pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens["August"])
        self.pushover = pushover

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
            cfg = get_config()
            self.session = aiohttp.ClientSession()
            from yalexs.const import Brand

            # August revoked the current yalexs API key for Brand.AUGUST; fall
            # back to the legacy key before any auth/session call uses it.
            apply_working_api_key(self.logger)
            # Auth uses AUGUST brand, but API endpoints moved to YALE_AUGUST
            self.api_auth = ApiAsync(self.session, brand=Brand.AUGUST)
            self.api = ApiAsync(self.session, brand=Brand.YALE_AUGUST)
            # Use token caching to persist authentication across restarts
            cache_file = cfg.august.token_file
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            # Re-feed the cached install_id so re-auth after token expiry does
            # not look like a new device to August (which would force 2FA).
            install_id = load_cached_install_id(cache_file)
            self.authenticator = AuthenticatorAsync(
                self.api_auth,
                "email",
                self.email,
                self.password,
                install_id=install_id,
                access_token_cache_file=cache_file,
            )
            # Setup authentication - this initializes the _authentication property
            await self.authenticator.async_setup_authentication()
            # yalexs owns the token cache write; tighten perms after.
            ensure_secret_perms(cache_file)

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None
            self.api = None
            self.api_auth = None
            self.authenticator = None

    async def authenticate(self) -> bool:
        await self._ensure_session()
        try:
            assert self.authenticator is not None
            self.logger.debug("Attempting August authentication...")
            # Proactively renew before expiry: yalexs only re-auths once the
            # token is fully expired, which leaves a gap until the next cron
            # run. When we are inside the renewal window (last 7 days) force a
            # password re-auth so August issues a fresh 30-day token now. The
            # cached install_id (fed via the constructor) is preserved so this
            # does not trigger 2FA.
            if self.authenticator.should_refresh():
                self.logger.info("August token inside renewal window; renewing now")
                self.authenticator._authentication = Authentication(
                    AuthenticationState.REQUIRES_AUTHENTICATION,
                    install_id=self.authenticator._authentication.install_id,
                )
            auth_result = await self.authenticator.async_authenticate()
            # yalexs may have (re)written the token cache; tighten perms.
            ensure_secret_perms(get_config().august.token_file)

            if auth_result is None:
                self.logger.error("Authentication returned None - check credentials")
                self.pushover.send_message(
                    "August auth returned None — check credentials",
                    title="August Auth Failure",
                    priority=1,
                )
                return False

            self.logger.debug(f"Authentication result state: {auth_result.state}")

            if auth_result.state == AuthenticationState.AUTHENTICATED:
                self.access_token = auth_result.access_token
                self.logger.info("Successfully authenticated with August API")
                return True
            elif auth_result.state == AuthenticationState.REQUIRES_VALIDATION:
                self.logger.error("August authentication requires 2FA validation")
                self.logger.error("Please complete 2FA in the August app and try again")
                self.pushover.send_message(
                    "August requires 2FA — run: uv run python August/validate_2fa.py",
                    title="August Auth Failure",
                    priority=1,
                )
                return False
            else:
                self.logger.error(f"August authentication failed: {auth_result.state}")
                self.pushover.send_message(
                    f"August auth failed: {auth_result.state}",
                    title="August Auth Failure",
                    priority=1,
                )
                return False

        except Exception as e:
            self.logger.error(f"Error during August authentication: {e}")
            self.logger.error(
                "Make sure august.email and august.password are correct in config/local.yaml"
            )
            self.pushover.send_message(
                f"August auth error: {e}",
                title="August Auth Failure",
                priority=1,
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
        *,
        client: Optional[AugustClient] = None,
        pushover: Optional[Notifier] = None,
        state_file: Optional[str] = None,
    ):
        # Injectable client + pushover + state_file path so tests never touch
        # real config or send real Pushover messages. See AugustClient.__init__.
        if pushover is None or state_file is None:
            cfg = get_config()
            if pushover is None:
                pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens["August"])
            if state_file is None:
                state_file = f"{cfg.paths.logging_dir}/august_monitor_state.json"
        if client is None:
            client = AugustClient(email, password, phone, pushover=pushover)
        self.client = client
        self.unlock_threshold = unlock_threshold_minutes * 60
        self.ajar_threshold = ajar_threshold_minutes * 60
        self.battery_threshold_pct = battery_threshold_pct
        self.battery_alert_cooldown = battery_alert_cooldown_minutes * 60
        self.door_alert_cooldown = door_alert_cooldown_minutes * 60
        self.logger = get_logger(__name__)
        self.pushover = pushover
        self.unlock_start_times: Dict[str, float] = {}
        self.ajar_start_times: Dict[str, float] = {}
        self.last_unlock_alerts: Dict[str, float] = {}
        self.last_ajar_alerts: Dict[str, float] = {}
        self.last_battery_alerts: Dict[str, float] = {}
        self.last_lock_failure_alerts: Dict[str, float] = {}
        # Track unknown status for recovery
        self.unknown_status_start_times: Dict[str, float] = {}
        self.unknown_threshold = 30 * 60  # 30 minutes
        self.state_file = state_file
        # Pending alerts for consolidation: (lock_name, alert_type, message)
        self.pending_alerts: list[tuple[str, str, str]] = []
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

            # Send consolidated alerts for this check cycle
            self._send_consolidated_alerts()

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
                    priority=-1,
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
                self.pushover.send_message(message, title="August Door Closed", priority=-1)

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
        message = f"{status.lock_name} unlocked for {minutes_unlocked:.0f} min"
        self.pending_alerts.append((status.lock_name, "unlock", message))
        self.logger.warning(f"Queued unlock alert: {message}")

    async def _send_door_ajar_alert(
        self, lock_id: str, status: LockState, ajar_duration: float
    ) -> None:
        minutes_ajar = ajar_duration / 60
        message = f"{status.lock_name} door ajar for {minutes_ajar:.0f} min"
        self.pending_alerts.append((status.lock_name, "ajar", message))
        self.logger.warning(f"Queued door ajar alert: {message}")

    def _send_consolidated_alerts(self) -> None:
        """Send consolidated notification for all pending alerts."""
        if not self.pending_alerts:
            return

        # Group by lock, track alert types
        alerts_by_lock: dict[str, list[tuple[str, str]]] = {}
        for lock_name, alert_type, message in self.pending_alerts:
            if lock_name not in alerts_by_lock:
                alerts_by_lock[lock_name] = []
            alerts_by_lock[lock_name].append((alert_type, message))

        # Build consolidated message: skip unlock if ajar exists (door open implies unlocked)
        messages = []
        for lock_name, alerts in alerts_by_lock.items():
            alert_types = {a[0] for a in alerts}
            if "ajar" in alert_types:
                # Only include ajar alert, skip unlock (redundant)
                messages.extend([a[1] for a in alerts if a[0] == "ajar"])
            else:
                messages.extend([a[1] for a in alerts])

        title = "🚪 August Alert" if len(alerts_by_lock) == 1 else "🚪 August Alerts"
        try:
            self.pushover.send_message("\n".join(messages), title=title, priority=1)
            self.logger.warning(f"Sent consolidated alert: {messages}")
        except Exception as e:
            self.logger.error(f"Failed to send consolidated alert: {e}")

        self.pending_alerts = []

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

                # If unknown for > 30 minutes, attempt recovery
                if unknown_duration >= self.unknown_threshold:
                    self.logger.warning(
                        f"Lock {status.lock_name} has been UNKNOWN for {unknown_duration / 60:.1f} minutes. "
                        f"Attempting lock recovery sequence."
                    )

                    # Attempt lock command (unlock was commented out)
                    lock_success = await self.client.lock_lock(lock_id)
                    if lock_success:
                        self.logger.info(f"Successfully sent lock command for {status.lock_name}")
                        # Send notification about recovery attempt
                        message = (
                            f"Attempted recovery for {status.lock_name} "
                            f"(unknown status for {unknown_duration / 60:.1f} min). "
                            f"Sent lock command."
                        )
                    else:
                        message = f"Failed to send lock command for {status.lock_name}"
                    self.pushover.send_message(message, title="🔧 August Lock Recovery", priority=1)

                    # Clear tracking after recovery attempt to prevent repeated attempts
                    self.unknown_status_start_times.pop(lock_id, None)
        else:
            # Clear unknown tracking when status is resolved
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
