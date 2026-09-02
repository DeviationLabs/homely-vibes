"""Tests for the Deco local admin API client.

No patching: the router is replaced by a fake requests Session that speaks the
real wire format (RSA-wrapped sign, AES-wrapped data), so these tests actually
exercise the crypto rather than asserting on mocks.
"""

import base64
import json
from typing import Any, cast
from urllib.parse import parse_qs

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa

from NetworkCheck.deco_client import (
    DecoAPIError,
    DecoAuthError,
    DecoClient,
    _aes_decrypt,
    count_wireless_clients,
    _aes_encrypt,
    _byte_len,
    _rsa_encrypt,
)

# One key reused across tests -- generation is the slow part. 2048 because
# anything smaller trips CodeQL's py/weak-crypto-key, and the multi-block
# chunking this exercises is a function of plaintext length, not key size.
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUB = _KEY.public_key().public_numbers()
MASTER_MAC = "AA:BB:CC:DD:EE:FF"
FAKE_ADMIN_CRED = "fake-local-admin"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeDecoSession:
    """Stands in for the router. Encrypts replies with the client's own key."""

    def __init__(
        self,
        device_list: list[dict[str, Any]] | None = None,
        client_list: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cookies: dict[str, str] = {}
        self.calls: list[tuple[str, dict, str]] = []
        self.client: DecoClient | None = None
        self.login_error_code: int | None = None
        self.device_list = (
            device_list if device_list is not None else [{"role": "master", "mac": MASTER_MAC}]
        )
        self.client_list = client_list if client_list is not None else []
        # Reply with a well-formed but client_list-less result, the shape a
        # firmware change could produce.
        self.omit_client_list = False

    def _encrypt(self, payload: dict[str, Any]) -> str:
        assert self.client is not None
        blob = _aes_encrypt(
            self.client._aes_key.encode(),
            self.client._aes_iv.encode(),
            json.dumps(payload).encode(),
        )
        return base64.b64encode(blob).decode()

    def post(
        self,
        url: str,
        params: dict[str, str] | None = None,
        data: str | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        form = (params or {}).get("form")
        self.calls.append((url, params or {}, data or ""))

        if form == "keys":
            return FakeResponse(
                {"result": {"password": [format(_PUB.n, "x"), format(_PUB.e, "x")]}}
            )
        if form == "auth":
            return FakeResponse(
                {"result": {"key": [format(_PUB.n, "x"), format(_PUB.e, "x")], "seq": 4242}}
            )
        if form == "login":
            if self.login_error_code:
                body = {"error_code": self.login_error_code, "result": {"attemptsAllowed": 3}}
                return FakeResponse({"data": self._encrypt(body)})
            self.cookies["sysauth"] = "deadbeef"
            return FakeResponse(
                {"data": self._encrypt({"error_code": 0, "result": {"stok": "STOK123"}})}
            )
        if form == "device_list":
            return FakeResponse(
                {"data": self._encrypt({"result": {"device_list": self.device_list}})}
            )
        if form == "client_list":
            result: dict[str, Any] = (
                {} if self.omit_client_list else {"client_list": self.client_list}
            )
            return FakeResponse({"data": self._encrypt({"result": result})})
        if form == "system":
            return FakeResponse({"data": self._encrypt({"error_code": 0})})
        raise AssertionError(f"unexpected form={form}")


def make_client(session: FakeDecoSession, sleep: Any = lambda _s: None) -> DecoClient:
    # The fake implements exactly the slice of Session the client touches
    # (post + cookies); cast rather than patch, per the repo's DI convention.
    client = DecoClient(
        "http://192.168.x.x",
        "admin",
        FAKE_ADMIN_CRED,
        session=cast(requests.Session, session),
        sleep=sleep,
    )
    session.client = client
    return client


class FlakyDecoSession(FakeDecoSession):
    """Fails the first `fail_times` posts for one form, then behaves normally."""

    def __init__(self, form: str, fail_times: int, error: Exception) -> None:
        super().__init__()
        self.target_form = form
        self.fail_times = fail_times
        self.error = error
        self.attempts: dict[str, int] = {}

    def post(
        self,
        url: str,
        params: dict[str, str] | None = None,
        data: str | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        form = (params or {}).get("form", "")
        self.attempts[form] = self.attempts.get(form, 0) + 1
        if form == self.target_form and self.attempts[form] <= self.fail_times:
            raise self.error
        return super().post(url, params=params, data=data, **_kwargs)


class TestCrypto:
    def test_aes_round_trip(self) -> None:
        key, iv = b"1234567890123456", b"6543210987654321"
        assert _aes_decrypt(key, iv, _aes_encrypt(key, iv, b"payload")) == b"payload"

    def test_rsa_encrypt_chunks_and_decrypts(self) -> None:
        """TP-Link concatenates per-block hex; verify each block decrypts back."""
        # >2 blocks at 2048-bit (245 usable bytes/block after PKCS#1 header).
        plaintext = b"k=1" + b"x" * 600
        ciphertext_hex = _rsa_encrypt(_PUB.n, _PUB.e, plaintext)
        block_size = _byte_len(_PUB.n)

        raw = bytes.fromhex(ciphertext_hex)
        assert len(raw) % block_size == 0
        recovered = b"".join(
            _KEY.decrypt(raw[i : i + block_size], asym_padding.PKCS1v15())
            for i in range(0, len(raw), block_size)
        )
        assert recovered == plaintext

    def test_byte_len_matches_key_size(self) -> None:
        assert _byte_len(_PUB.n) == 256


class TestLogin:
    def test_login_sets_stok_and_requires_cookie(self) -> None:
        session = FakeDecoSession()
        client = make_client(session)
        client.login()
        assert client._stok == "STOK123"
        assert "sysauth" in session.cookies

    def test_login_body_is_signed_and_encrypted(self) -> None:
        session = FakeDecoSession()
        client = make_client(session)
        client.login()

        _, _, body = next(c for c in session.calls if c[1].get("form") == "login")
        fields = parse_qs(body)
        assert set(fields) == {"sign", "data"}

        payload = json.loads(
            _aes_decrypt(
                client._aes_key.encode(),
                client._aes_iv.encode(),
                base64.b64decode(fields["data"][0]),
            )
        )
        assert payload["operation"] == "login"
        assert "password" in payload["params"]

    def test_sign_carries_seq_plus_data_length(self) -> None:
        session = FakeDecoSession()
        client = make_client(session)
        client.login()

        _, _, body = next(c for c in session.calls if c[1].get("form") == "login")
        fields = parse_qs(body)
        sign_raw = bytes.fromhex(fields["sign"][0])
        block = _byte_len(_PUB.n)
        sign_text = b"".join(
            _KEY.decrypt(sign_raw[i : i + block], asym_padding.PKCS1v15())
            for i in range(0, len(sign_raw), block)
        ).decode()

        expected_s = 4242 + len(fields["data"][0])
        assert f"s={expected_s}" in sign_text
        assert f"k={client._aes_key}" in sign_text
        assert f"i={client._aes_iv}" in sign_text

    def test_bad_password_raises_auth_error(self) -> None:
        session = FakeDecoSession()
        session.login_error_code = -5002
        client = make_client(session)
        with pytest.raises(DecoAuthError, match="Invalid Deco admin password"):
            client.login()

    def test_missing_cookie_raises_api_error(self) -> None:
        session = FakeDecoSession()
        client = make_client(session)

        original_post = session.post

        def post_without_cookie(*args: Any, **kwargs: Any) -> FakeResponse:
            response = original_post(*args, **kwargs)
            session.cookies.pop("sysauth", None)
            return response

        session.post = post_without_cookie  # type: ignore[method-assign]
        with pytest.raises(DecoAPIError, match="sysauth cookie"):
            client.login()


class TestOperations:
    def test_reboot_sends_mac_list(self) -> None:
        session = FakeDecoSession()
        client = make_client(session)
        client.reboot([MASTER_MAC])

        _, _, body = next(c for c in session.calls if c[1].get("form") == "system")
        payload = json.loads(
            _aes_decrypt(
                client._aes_key.encode(),
                client._aes_iv.encode(),
                base64.b64decode(parse_qs(body)["data"][0]),
            )
        )
        assert payload == {
            "operation": "reboot",
            "params": {"mac_list": [{"mac": MASTER_MAC}]},
        }

    def test_reboot_with_no_macs_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_client(FakeDecoSession()).reboot([])

    def test_reboot_logs_in_first(self) -> None:
        session = FakeDecoSession()
        client = make_client(session)
        client.reboot([MASTER_MAC])
        assert [c[1].get("form") for c in session.calls][:3] == ["keys", "auth", "login"]

    def test_list_clients_asks_for_every_deco(self) -> None:
        """`device_mac: default` is what makes this the whole-mesh census."""
        session = FakeDecoSession(client_list=[{"connection_type": "band5"}])
        client = make_client(session)
        assert client.list_clients() == [{"connection_type": "band5"}]

        _, _, body = next(c for c in session.calls if c[1].get("form") == "client_list")
        payload = json.loads(
            _aes_decrypt(
                client._aes_key.encode(),
                client._aes_iv.encode(),
                base64.b64decode(parse_qs(body)["data"][0]),
            )
        )
        assert payload == {"operation": "read", "params": {"device_mac": "default"}}

    def test_a_malformed_client_list_is_an_error_not_an_empty_census(self) -> None:
        """An empty census reboots the mesh, so it must never be a fallback."""
        session = FakeDecoSession()
        session.omit_client_list = True
        with pytest.raises(DecoAPIError, match="Unexpected client_list response"):
            make_client(session).list_clients()


class TestWirelessCensus:
    """Counting is the whole decision, so the edges matter more than usual."""

    def test_wired_clients_do_not_count(self) -> None:
        clients = [{"connection_type": "wired"}, {"connection_type": "band5"}]
        assert count_wireless_clients(clients) == 1

    def test_both_radios_count(self) -> None:
        clients = [{"connection_type": "band2_4"}, {"connection_type": "band5"}]
        assert count_wireless_clients(clients) == 2

    def test_offline_clients_do_not_count(self) -> None:
        clients = [{"connection_type": "band5", "online": False}]
        assert count_wireless_clients(clients) == 0

    def test_a_missing_online_field_counts_as_present(self) -> None:
        """Some firmware omits it; presence in the list is then the signal."""
        assert count_wireless_clients([{"connection_type": "band5"}]) == 1

    def test_an_unknown_connection_type_counts_as_wireless(self) -> None:
        """Fail-safe direction: `band6` must not read as zero radios and
        reboot a house whose Wi-Fi is perfectly fine.
        """
        assert count_wireless_clients([{"connection_type": "band6"}]) == 1

    def test_a_missing_connection_type_counts_as_wireless(self) -> None:
        assert count_wireless_clients([{}]) == 1

    def test_case_does_not_change_the_verdict(self) -> None:
        assert count_wireless_clients([{"connection_type": "WIRED"}]) == 0


class TestTransientRetry:
    """A transient timeout must not abort a real reboot (bk-22).

    The watchdog calls list_decos() inside _execute to learn which units to
    reboot. One dropped packet there used to abort the whole recovery and fire
    a P1, on a mesh that was fine.
    """

    def test_list_decos_survives_a_transient_timeout(self) -> None:
        session = FlakyDecoSession("device_list", 1, requests.Timeout("boom"))
        slept: list[float] = []
        client = make_client(session, sleep=slept.append)
        assert [d["mac"] for d in client.list_decos()] == [MASTER_MAC]
        assert session.attempts["device_list"] == 2
        assert slept, "expected a backoff between attempts"

    def test_retries_are_bounded_and_then_raise(self) -> None:
        session = FlakyDecoSession("device_list", 99, requests.ConnectionError("down"))
        client = make_client(session)
        with pytest.raises(DecoAPIError, match="attempt"):
            client.list_decos()
        assert session.attempts["device_list"] == 3

    def test_reboot_is_never_retried(self) -> None:
        """A lost reboot response is ambiguous -- it may have landed. Re-issuing
        can bounce a mesh that is already coming back up, so one attempt only."""
        session = FlakyDecoSession("system", 1, requests.Timeout("boom"))
        client = make_client(session)
        with pytest.raises(DecoAPIError):
            client.reboot([MASTER_MAC])
        assert session.attempts["system"] == 1

    def test_http_errors_are_not_retried(self) -> None:
        """A 4xx/5xx is a real answer from the router; repeating it just repeats
        the rejection."""
        session = FlakyDecoSession("device_list", 1, requests.HTTPError("500"))
        client = make_client(session)
        with pytest.raises(DecoAPIError):
            client.list_decos()
        assert session.attempts["device_list"] == 1
