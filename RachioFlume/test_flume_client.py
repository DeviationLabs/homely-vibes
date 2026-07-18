"""Tests for FlumeClient token refresh: proactive near-expiry re-auth and
reactive re-auth-and-retry on 401.

Uses an injected fake session (no patch()): auth goes through `.post`, API
calls through `.request`, so the fake can script API responses while minting
a fresh token on every auth call.
"""

import json
from datetime import datetime, timedelta

import pytest
import requests

from RachioFlume.flume_client import FlumeClient

_DEVICES_PAYLOAD = {
    "success": True,
    "data": [{"id": "dev1", "type": 2, "connected": True, "location_id": None}],
}


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class FakeFlumeSession:
    """Scripted session: every `.post` (auth) mints token `tok<N>`; `.request`
    (API) pops the next scripted response and records the bearer used."""

    def __init__(self, api_responses: list[FakeResponse]):
        self.auth_calls = 0
        self.api_bearers: list[str] = []
        self._api_responses = list(api_responses)

    def post(self, url: str, json: dict | None = None, headers: dict | None = None) -> FakeResponse:
        self.auth_calls += 1
        return FakeResponse(
            200,
            {
                "success": True,
                "data": [{"access_token": f"tok{self.auth_calls}", "expires_in": 604800}],
            },
        )

    def request(
        self, method: str, url: str, headers: dict | None = None, **kwargs: object
    ) -> FakeResponse:
        self.api_bearers.append((headers or {}).get("Authorization", ""))
        return self._api_responses.pop(0)


def _client(session: FakeFlumeSession) -> FlumeClient:
    return FlumeClient(
        client_id="cid",
        client_secret="csec",  # nosecret
        username="user@example.com",
        password="pw",  # nosecret
        session=session,  # type: ignore[arg-type]
    )


def test_reauth_and_retry_on_401() -> None:
    session = FakeFlumeSession([FakeResponse(401), FakeResponse(200, _DEVICES_PAYLOAD)])
    client = _client(session)
    assert session.auth_calls == 1

    devices = client.get_devices()

    assert [d.id for d in devices] == ["dev1"]
    assert session.auth_calls == 2  # re-authenticated after the 401
    assert session.api_bearers == ["Bearer tok1", "Bearer tok2"]  # retry used new token


def test_persistent_401_raises_after_single_retry() -> None:
    session = FakeFlumeSession([FakeResponse(401), FakeResponse(401)])
    client = _client(session)

    with pytest.raises(requests.HTTPError):
        client.get_devices()

    assert session.auth_calls == 2  # exactly one re-auth attempt, no retry loop


def test_proactive_reauth_near_token_expiry() -> None:
    session = FakeFlumeSession([FakeResponse(200, _DEVICES_PAYLOAD)])
    client = _client(session)

    # Age the token past the refresh fraction of its lifetime.
    client._token_acquired_at = datetime.now() - timedelta(
        seconds=client._token_lifetime_seconds * client.TOKEN_REFRESH_FRACTION + 1
    )
    client.get_devices()

    assert session.auth_calls == 2  # refreshed before the request
    assert session.api_bearers == ["Bearer tok2"]


def test_fresh_token_is_not_refreshed() -> None:
    session = FakeFlumeSession([FakeResponse(200, _DEVICES_PAYLOAD)])
    client = _client(session)

    client.get_devices()

    assert session.auth_calls == 1
    assert session.api_bearers == ["Bearer tok1"]


def test_init_stores_credentials() -> None:
    client = _client(FakeFlumeSession([]))
    assert client.client_id == "cid"
    assert client.client_secret == "csec"  # nosecret
    assert client.username == "user@example.com"
    assert client.password == "pw"  # nosecret


def test_get_devices_parses_multiple_and_active_flag() -> None:
    payload = {
        "success": True,
        "data": [
            {"id": "device1", "type": 2, "connected": True, "location_id": None},
            {"id": "device2", "type": 2, "connected": False, "location_id": None},
        ],
    }
    client = _client(FakeFlumeSession([FakeResponse(200, payload)]))

    devices = client.get_devices()

    assert [d.id for d in devices] == ["device1", "device2"]
    assert all("Water Sensor" in d.name for d in devices)
    assert [d.active for d in devices] == [True, False]


def test_get_devices_skips_non_meter_bridge() -> None:
    payload = {
        "success": True,
        "data": [
            {"id": "bridge1", "type": 1, "connected": True, "location_id": None},
            {"id": "meter1", "type": 2, "connected": True, "location_id": None},
        ],
    }
    client = _client(FakeFlumeSession([FakeResponse(200, payload)]))

    devices = client.get_devices()

    assert [d.id for d in devices] == ["meter1"]


def test_get_usage_parses_readings() -> None:
    usage_payload = {
        "data": [
            {
                "data": [
                    {"datetime": "2023-01-01 10:00:00", "value": 1.5},
                    {"datetime": "2023-01-01 10:01:00", "value": 2.0},
                ]
            }
        ]
    }
    client = _client(
        FakeFlumeSession([FakeResponse(200, _DEVICES_PAYLOAD), FakeResponse(200, usage_payload)])
    )

    readings = client.get_usage(datetime(2023, 1, 1, 10, 0), datetime(2023, 1, 1, 10, 2))

    assert [r.value for r in readings] == [1.5, 2.0]
    assert readings[0].timestamp == datetime(2023, 1, 1, 10, 0)
