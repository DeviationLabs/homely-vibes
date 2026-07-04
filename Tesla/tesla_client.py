#!/usr/bin/env python3
"""Tesla Fleet API client with sync interface compatible with manage_power.py.

Wraps the async `tesla_fleet_api` SDK in a synchronous facade. Each public
call runs its own `asyncio.run()` — overhead is negligible for the polling
cadence used here (default 3 minutes).

Token file shape (config/tokens/tesla_tokens.json):
    {
      "access_token": "...",
      "refresh_token": "...",
      "expires_at": <unix-int>,
      "token_type": "Bearer"
    }
"""

import asyncio
import json
import os
import threading
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from tesla_fleet_api.exceptions import TeslaFleetError
from tesla_fleet_api.tesla import EnergySite, TeslaFleetOAuth

from lib.config import get_config
from lib.logger import get_logger


class TeslaAuthError(Exception):
    """Authentication failed."""


class TeslaTokenExpiredError(Exception):
    """Token expired and refresh failed."""


class TeslaAPIError(Exception):
    """Tesla API request error."""


T = TypeVar("T")


class TeslaAPIClient:
    """Sync facade over tesla_fleet_api's async OAuth + EnergySites surface."""

    def __init__(self, token_file: Optional[str] = None):
        cfg = get_config()
        self.token_file = os.path.expanduser(token_file or cfg.tesla.tesla_token_file)
        if not os.path.isabs(self.token_file):
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            self.token_file = os.path.join(project_root, self.token_file)
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)

        self.client_id = cfg.tesla.fleet_client_id
        self.client_secret = cfg.tesla.fleet_client_secret
        self.redirect_uri = cfg.tesla.fleet_redirect_uri
        self.region = cfg.tesla.fleet_region or "na"

        if not self.client_id or not self.client_secret:
            raise TeslaAuthError(
                "Fleet API client_id/client_secret not configured. "
                "Set tesla.fleet_client_id and tesla.fleet_client_secret in config/local.yaml."
            )

        self._lock = threading.Lock()
        self.logger = get_logger(__name__)

    def _load_tokens(self) -> Dict[str, Any]:
        try:
            with open(self.token_file) as f:
                tokens: Dict[str, Any] = json.load(f)
                return tokens
        except FileNotFoundError:
            raise TeslaTokenExpiredError(
                f"Token file not found: {self.token_file}. Run: uv run Tesla/tesla_auth.py"
            )
        except json.JSONDecodeError as e:
            raise TeslaAuthError(f"Invalid token file format: {e}")

    def _save_tokens_from_oauth(self, oauth: TeslaFleetOAuth) -> None:
        token_data = {
            "access_token": oauth._access_token,
            "refresh_token": oauth.refresh_token,
            "expires_at": int(oauth.expires),
            "token_type": "Bearer",
        }
        with open(self.token_file, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(self.token_file, 0o600)
        self.logger.debug(f"Tokens persisted to {self.token_file}")

    async def _with_oauth(self, fn: Callable[[TeslaFleetOAuth], Awaitable[T]]) -> T:
        with self._lock:
            tokens = self._load_tokens()
            original_access = tokens["access_token"]

        async with aiohttp.ClientSession() as session:
            oauth = TeslaFleetOAuth(
                session=session,
                region=self.region,  # type: ignore[arg-type]
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                expires=int(tokens["expires_at"]),
            )

            try:
                await oauth.check_access_token()
            except Exception as e:
                raise TeslaTokenExpiredError(
                    f"Token refresh failed - run: uv run Tesla/tesla_auth.py. Cause: {e}"
                )

            try:
                result = await fn(oauth)
            except aiohttp.ClientResponseError as e:
                if e.status == 401:
                    raise TeslaTokenExpiredError(
                        "Authentication failed - run: uv run Tesla/tesla_auth.py"
                    )
                if e.status == 429:
                    raise TeslaAPIError("Rate limited - retry later")
                raise TeslaAPIError(f"API error: {e.status} - {e.message}")

            with self._lock:
                if oauth.access_token != original_access:
                    self._save_tokens_from_oauth(oauth)

            return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(TeslaFleetError),
        reraise=True,
    )
    def _run_once(self, fn: Callable[[TeslaFleetOAuth], Awaitable[T]]) -> T:
        return asyncio.run(self._with_oauth(fn))

    def _run(self, fn: Callable[[TeslaFleetOAuth], Awaitable[T]]) -> T:
        # tesla_fleet_api's TeslaFleetError subclasses BaseException, not Exception,
        # so upstream 5xx/etc bypass normal `except Exception` retry blocks. Retry
        # transient failures up to 3x, then rewrap so callers get a regular
        # Exception subclass.
        try:
            return self._run_once(fn)
        except TeslaFleetError as e:
            raise TeslaAPIError(f"{type(e).__name__}: {e}") from e

    def get_energy_sites(self) -> List[Dict[str, Any]]:
        async def call(oauth: TeslaFleetOAuth) -> List[Dict[str, Any]]:
            resp = await oauth.products()
            products = resp.get("response", [])
            return [p for p in products if p.get("resource_type") == "battery"]

        return self._run(call)


class BatteryProduct:
    """Compatibility wrapper preserving the dict-like interface used by manage_power.py."""

    def __init__(self, site_data: Dict[str, Any], client: TeslaAPIClient):
        self._data: Dict[str, Any] = dict(site_data)
        self._client = client
        self.site_id: int = int(site_data["energy_site_id"])

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_site_info(self) -> "BatteryProduct":
        async def call(oauth: TeslaFleetOAuth) -> Dict[str, Any]:
            site = EnergySite(oauth, self.site_id)
            return await site.site_info()

        resp = self._client._run(call)
        self._data.update(resp.get("response", {}))
        return self

    def get_site_data(self) -> "BatteryProduct":
        async def call(oauth: TeslaFleetOAuth) -> Dict[str, Any]:
            site = EnergySite(oauth, self.site_id)
            return await site.live_status()

        resp = self._client._run(call)
        self._data.update(resp.get("response", {}))
        return self

    def set_operation(self, mode: str) -> str:
        async def call(oauth: TeslaFleetOAuth) -> Dict[str, Any]:
            site = EnergySite(oauth, self.site_id)
            return await site.operation(default_real_mode=mode)

        resp = self._client._run(call)
        return str(resp.get("response", {}).get("message", "Updated"))

    def set_backup_reserve_percent(self, percent: int) -> str:
        async def call(oauth: TeslaFleetOAuth) -> Dict[str, Any]:
            site = EnergySite(oauth, self.site_id)
            return await site.backup(backup_reserve_percent=int(percent))

        resp = self._client._run(call)
        return str(resp.get("response", {}).get("message", "Updated"))


__all__ = [
    "TeslaAPIClient",
    "BatteryProduct",
    "TeslaAuthError",
    "TeslaTokenExpiredError",
    "TeslaAPIError",
]


if __name__ == "__main__":
    # Quick connectivity check
    logger = get_logger(__name__)
    client = TeslaAPIClient()
    sites = client.get_energy_sites()
    logger.info(f"Found {len(sites)} battery site(s)")
    for s in sites:
        logger.info(f"  - {s.get('site_name')} (id={s.get('energy_site_id')})")
