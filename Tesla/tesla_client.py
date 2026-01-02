#!/usr/bin/env python3
"""Direct Tesla Owner API client replacing TeslaPy."""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from lib.logger import get_logger


class TeslaAuthError(Exception):
    """Authentication failed."""

    pass


class TeslaTokenExpiredError(Exception):
    """Token expired and refresh failed."""

    pass


class TeslaAPIError(Exception):
    """Tesla API request error."""

    pass


class TeslaAPIClient:
    """Direct Tesla Owner API client with auto-refresh token management."""

    BASE_URL = "https://owner-api.teslamotors.com/"
    TOKEN_URL = "https://auth.tesla.com/oauth2/v3/token"
    TOKEN_REFRESH_BUFFER = 300  # Refresh 5 minutes before expiry

    def __init__(self, token_file: str = "~/logs/tesla_tokens.json"):
        self.token_file = os.path.expanduser(token_file)
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "User-Agent": "TeslaApp/4.10.0"}
        )
        self._tokens: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self.logger = get_logger(__name__)

    def _load_tokens(self) -> Dict[str, Any]:
        """Load tokens from file."""
        try:
            with open(self.token_file) as f:
                return json.load(f)
        except FileNotFoundError:
            raise TeslaTokenExpiredError(
                f"Token file not found: {self.token_file}. Run: python Tesla/tesla_auth.py"
            )
        except json.JSONDecodeError as e:
            raise TeslaAuthError(f"Invalid token file format: {e}")

    def _save_tokens(self, tokens: Dict[str, Any]) -> None:
        """Save tokens to file with proper permissions."""
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        os.chmod(self.token_file, 0o600)
        self.logger.debug(f"Tokens saved to {self.token_file}")

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or will expire soon."""
        if not self._tokens:
            return True
        return self._tokens["expires_at"] < time.time() + self.TOKEN_REFRESH_BUFFER

    def _refresh_access_token(self) -> None:
        """Refresh access token using refresh token."""
        with self._lock:
            tokens = self._load_tokens()

            self.logger.info("Refreshing access token")

            try:
                response = self.session.post(
                    self.TOKEN_URL,
                    json={
                        "grant_type": "refresh_token",
                        "client_id": "ownerapi",
                        "refresh_token": tokens["refresh_token"],
                    },
                    timeout=10,
                )
                response.raise_for_status()
            except requests.HTTPError as e:
                if e.response.status_code == 400:
                    raise TeslaTokenExpiredError(
                        "Refresh token invalid - run: python Tesla/tesla_auth.py"
                    )
                raise TeslaAPIError(f"Token refresh failed: {e}")
            except requests.RequestException as e:
                raise TeslaAPIError(f"Token refresh network error: {e}")

            new_tokens = response.json()
            tokens.update(
                {
                    "access_token": new_tokens["access_token"],
                    "refresh_token": new_tokens.get("refresh_token", tokens["refresh_token"]),
                    "expires_at": int(time.time()) + new_tokens["expires_in"],
                    "token_type": new_tokens["token_type"],
                }
            )

            self._save_tokens(tokens)
            self._tokens = tokens
            self.logger.info("Access token refreshed successfully")

    def _ensure_valid_token(self) -> None:
        """Ensure we have a valid access token."""
        if not self._tokens:
            self._tokens = self._load_tokens()

        if self._is_token_expired():
            self._refresh_access_token()

    def _request(
        self, method: str, endpoint: str, retry_on_401: bool = True, **kwargs
    ) -> Dict[str, Any]:
        """Make authenticated API request with auto-retry on 401."""
        self._ensure_valid_token()

        url = urljoin(self.BASE_URL, endpoint)
        headers = {"Authorization": f"Bearer {self._tokens['access_token']}"}

        self.logger.debug(f"{method} {endpoint}")

        try:
            response = self.session.request(method, url, headers=headers, timeout=30, **kwargs)

            # Handle token expiry with one retry
            if response.status_code == 401 and retry_on_401:
                self.logger.warning("Got 401, refreshing token and retrying")
                self._refresh_access_token()
                headers = {"Authorization": f"Bearer {self._tokens['access_token']}"}
                response = self.session.request(method, url, headers=headers, timeout=30, **kwargs)

            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            if e.response.status_code == 429:
                raise TeslaAPIError("Rate limited - retry later")
            elif e.response.status_code == 401:
                raise TeslaTokenExpiredError(
                    "Authentication failed - run: python Tesla/tesla_auth.py"
                )
            else:
                raise TeslaAPIError(f"API error: {e.response.status_code} - {e.response.text}")
        except requests.Timeout:
            raise TeslaAPIError("Request timeout")
        except requests.ConnectionError as e:
            raise TeslaAPIError(f"Connection failed: {e}")

    def get_energy_sites(self) -> List[Dict[str, Any]]:
        """Get list of energy sites (batteries)."""
        response = self._request("GET", "api/1/products")
        products = response["response"]
        return [p for p in products if p.get("resource_type") == "battery"]

    def get_site_info(self, site_id: int) -> Dict[str, Any]:
        """Get site configuration."""
        response = self._request("GET", f"api/1/energy_sites/{site_id}/site_info")
        return response["response"]

    def get_site_data(self, site_id: int) -> Dict[str, Any]:
        """Get live site status."""
        response = self._request("GET", f"api/1/energy_sites/{site_id}/live_status")
        return response["response"]

    def set_operation_mode(self, site_id: int, mode: str) -> str:
        """Set operation mode (self_consumption, backup, autonomous)."""
        response = self._request(
            "POST", f"api/1/energy_sites/{site_id}/operation", json={"default_real_mode": mode}
        )
        return response["response"].get("message", "Updated")

    def set_backup_reserve(self, site_id: int, percent: int) -> str:
        """Set backup reserve percentage."""
        response = self._request(
            "POST",
            f"api/1/energy_sites/{site_id}/backup",
            json={"backup_reserve_percent": int(percent)},
        )
        return response["response"].get("message", "Updated")


class BatteryProduct:
    """Wrapper to maintain TeslaPy-like interface for compatibility."""

    def __init__(self, site_data: Dict[str, Any], client: TeslaAPIClient):
        self._data = site_data
        self._client = client
        self.site_id = site_data["energy_site_id"]

    def __getitem__(self, key: str) -> Any:
        """Dict-like access to data."""
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like get method."""
        return self._data.get(key, default)

    def get_site_info(self) -> "BatteryProduct":
        """Update with site info."""
        info = self._client.get_site_info(self.site_id)
        self._data.update(info)
        return self

    def get_site_data(self) -> "BatteryProduct":
        """Update with live status."""
        data = self._client.get_site_data(self.site_id)
        self._data.update(data)
        return self

    def set_operation(self, mode: str) -> str:
        """Set operation mode."""
        return self._client.set_operation_mode(self.site_id, mode)

    def set_backup_reserve_percent(self, percent: int) -> str:
        """Set backup reserve."""
        return self._client.set_backup_reserve(self.site_id, percent)
