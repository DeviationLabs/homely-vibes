"""Tests for the Xfinity gateway client.

No patching: a fake requests Session stands in for the device and serves the
real page shapes, so the CSRF scrape and the payload are genuinely exercised.

The load-bearing test here is `test_the_payload_is_the_reboot_button`. The same
endpoint with the same payload shape performs a factory wipe one identifier
away, so the exact bytes we send are a correctness property, not a detail.
"""

import json
from typing import Any, Optional, cast
from urllib.parse import parse_qs

import pytest
import requests

from NetworkCheck.modem_client import ModemAPIError, ModemAuthError, ModemClient

HOST = "http://10.0.0.x"
FAKE_ADMIN_CRED = "fake-modem-admin"
TOKEN = "42sam6l8rt"

REBOOT_PAGE = f"""
<html><head><title>XFINITY</title></head><body>
<script>
function setResetInfo(info) {{
    var token = "{TOKEN}";
    $.ajax({{ type: "POST", url: "actionHandler/ajaxSet_Reset_Restore.jst",
             data: {{ resetInfo: jsonInfo, csrfp_token: token }} }});
}}
</script>
<a id="btn1" title="Reset the Gateway"></a>
<a id="btn5" title="Restore Factory settings"></a>
</body></html>
"""

LOGIN_PAGE = '<form action="check.jst" method="post"><input name="username"></form>'


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeGateway:
    """Stands in for the modem. Records what it was asked to do."""

    def __init__(
        self,
        reboot_body: str = '{"reboot": true}',
        page: str = REBOOT_PAGE,
        set_cookie: bool = True,
    ) -> None:
        self.cookies: dict[str, str] = {}
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.reboot_body = reboot_body
        self.page = page
        self.set_cookie = set_cookie

    def post(self, url: str, data: Optional[dict] = None, **_kwargs: Any) -> FakeResponse:  # noqa: ANN401
        self.posts.append((url, data or {}))
        if url.endswith("/check.jst"):
            if self.set_cookie:
                self.cookies["DUKSID"] = "session"
            return FakeResponse("")
        if url.endswith("ajaxSet_Reset_Restore.jst"):
            return FakeResponse(self.reboot_body)
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url: str, **_kwargs: Any) -> FakeResponse:  # noqa: ANN401
        assert url.endswith("/restore_reboot.jst")
        return FakeResponse(self.page)


def make_client(gateway: FakeGateway) -> ModemClient:
    return ModemClient(HOST, "admin", FAKE_ADMIN_CRED, session=cast(requests.Session, gateway))


class TestReboot:
    def test_the_payload_is_the_reboot_button(self) -> None:
        """btn5 on this same endpoint is a factory wipe. Pin the bytes."""
        gateway = FakeGateway()
        make_client(gateway).reboot()

        url, data = gateway.posts[-1]
        assert url.endswith("/actionHandler/ajaxSet_Reset_Restore.jst")
        assert json.loads(data["resetInfo"]) == ["btn1", "Device", "admin"]
        assert data["csrfp_token"] == TOKEN

    def test_it_logs_in_before_rebooting(self) -> None:
        gateway = FakeGateway()
        make_client(gateway).reboot()
        assert gateway.posts[0][0].endswith("/check.jst")

    def test_credentials_go_in_the_login_body(self) -> None:
        gateway = FakeGateway()
        make_client(gateway).reboot()
        _, data = gateway.posts[0]
        assert data == {"username": "admin", "password": FAKE_ADMIN_CRED}

    def test_the_csrf_token_comes_from_the_page_not_the_cookie(self) -> None:
        """The handler validates the scraped literal, not the cookie."""
        gateway = FakeGateway(page=REBOOT_PAGE.replace(TOKEN, "freshtoken"))
        make_client(gateway).reboot()
        assert gateway.posts[-1][1]["csrfp_token"] == "freshtoken"


class TestFailures:
    def test_missing_session_cookie_is_an_auth_error(self) -> None:
        gateway = FakeGateway(set_cookie=False)
        with pytest.raises(ModemAuthError, match="session cookie"):
            make_client(gateway).reboot()

    def test_being_bounced_to_the_login_form_is_an_auth_error(self) -> None:
        gateway = FakeGateway(page=LOGIN_PAGE)
        with pytest.raises(ModemAuthError, match="login form"):
            make_client(gateway).reboot()

    def test_a_page_without_a_token_is_an_api_error(self) -> None:
        """Button present so the guard passes; only the token is missing."""
        page = '<html><a id="btn1" title="Reset the Gateway"></a></html>'
        gateway = FakeGateway(page=page)
        with pytest.raises(ModemAPIError, match="no CSRF token"):
            make_client(gateway).reboot()

    def test_a_declined_reboot_is_not_reported_as_success(self) -> None:
        """It answers 200 with {"reboot": false}; that is a failure."""
        gateway = FakeGateway(reboot_body='{"reboot": false}')
        with pytest.raises(ModemAPIError, match="declined"):
            make_client(gateway).reboot()

    def test_a_non_json_reply_is_an_api_error(self) -> None:
        gateway = FakeGateway(reboot_body="<html>error</html>")
        with pytest.raises(ModemAPIError, match="not JSON"):
            make_client(gateway).reboot()

    def test_a_transport_failure_is_wrapped(self) -> None:
        class DeadGateway(FakeGateway):
            def post(self, url: str, data: Optional[dict] = None, **kwargs: Any) -> FakeResponse:
                raise requests.ConnectTimeout("no route to host")

        with pytest.raises(ModemAPIError, match="failed"):
            make_client(DeadGateway()).reboot()


class TestButtonGuard:
    """The runtime half of the contract: does the device still agree?

    Pinning the payload proves what we send. Only this proves the firmware
    still means "reboot" by it -- and the neighbouring id is a factory wipe.
    """

    def test_a_relabelled_button_refuses_to_post(self) -> None:
        page = REBOOT_PAGE.replace("Reset the Gateway", "Restore Factory settings")
        gateway = FakeGateway(page=page)
        with pytest.raises(ModemAPIError, match="refusing to POST"):
            make_client(gateway).reboot()
        assert not any("Reset_Restore" in url for url, _ in gateway.posts)

    def test_a_missing_button_refuses_to_post(self) -> None:
        page = REBOOT_PAGE.replace('<a id="btn1" title="Reset the Gateway"></a>', "")
        gateway = FakeGateway(page=page)
        with pytest.raises(ModemAPIError, match="absent from the reset page"):
            make_client(gateway).reboot()
        assert not any("Reset_Restore" in url for url, _ in gateway.posts)

    def test_the_label_check_tolerates_case_and_spacing(self) -> None:
        page = REBOOT_PAGE.replace('title="Reset the Gateway"', "title='  RESET THE GATEWAY '")
        make_client(FakeGateway(page=page)).reboot()

    def test_attribute_order_does_not_matter(self) -> None:
        page = REBOOT_PAGE.replace(
            '<a id="btn1" title="Reset the Gateway"></a>',
            '<a class="x" title="Reset the Gateway" id="btn1"></a>',
        )
        make_client(FakeGateway(page=page)).reboot()

    def test_a_relabelled_neighbour_is_irrelevant(self) -> None:
        """Only our own button's label gates the POST."""
        page = REBOOT_PAGE.replace("Restore Factory settings", "Something Else Entirely")
        make_client(FakeGateway(page=page)).reboot()


class TestVerify:
    """The daily read-only check. Must exercise everything but the POST."""

    def test_it_never_posts_to_the_reset_handler(self) -> None:
        gateway = FakeGateway()
        make_client(gateway).verify()
        assert not any("Reset_Restore" in url for url, _ in gateway.posts)

    def test_it_still_logs_in(self) -> None:
        gateway = FakeGateway()
        make_client(gateway).verify()
        assert gateway.posts[0][0].endswith("/check.jst")

    def test_it_reports_the_button_it_confirmed(self) -> None:
        assert "btn1" in make_client(FakeGateway()).verify()

    def test_a_bad_credential_surfaces_here(self) -> None:
        with pytest.raises(ModemAuthError):
            make_client(FakeGateway(set_cookie=False)).verify()

    def test_a_relabelled_button_surfaces_here(self) -> None:
        """The reason this check exists: catch a firmware renumbering on a
        healthy day rather than during the outage it was meant to fix.
        """
        page = REBOOT_PAGE.replace("Reset the Gateway", "Restore Factory settings")
        with pytest.raises(ModemAPIError, match="refusing"):
            make_client(FakeGateway(page=page)).verify()

    def test_a_missing_token_surfaces_here(self) -> None:
        page = '<html><a id="btn1" title="Reset the Gateway"></a></html>'
        with pytest.raises(ModemAPIError, match="no CSRF token"):
            make_client(FakeGateway(page=page)).verify()

    def test_verify_and_reboot_share_the_same_preparation(self) -> None:
        """Structural, so the check cannot drift from the thing checked.

        If someone adds a step to `reboot()` outside `_prepare()`, the daily
        check silently stops covering it -- which is exactly how a safety net
        rots. Both must reach the handler having made identical calls.
        """
        verified = FakeGateway()
        make_client(verified).verify()
        rebooted = FakeGateway()
        make_client(rebooted).reboot()

        assert [url for url, _ in verified.posts] == [
            url for url, _ in rebooted.posts if "Reset_Restore" not in url
        ]


class TestSurface:
    def test_reboot_takes_no_arguments(self) -> None:
        """There is deliberately no parameter to thread btn5 through."""
        import inspect

        params = inspect.signature(ModemClient.reboot).parameters
        assert list(params) == ["self"]

    def test_no_destructive_button_id_is_reachable_in_code(self) -> None:
        """The DANGER docstring names btn4/5/6 on purpose; code must not.

        Checked over the AST rather than the raw text, so documenting the
        hazard stays possible while a literal in an executable position -- the
        thing that could actually wipe the gateway -- fails the build.
        """
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(__file__).with_name("modem_client.py").read_text())

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                body = getattr(node, "body", [])
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    docstrings.add(id(body[0].value))

        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        for destructive in ("btn4", "btn5", "btn6"):
            assert not any(destructive in text for text in literals)

    def test_parse_qs_round_trip_of_the_payload(self) -> None:
        """Sanity: the payload survives form encoding unchanged."""
        gateway = FakeGateway()
        make_client(gateway).reboot()
        encoded = "&".join(f"{k}={v}" for k, v in gateway.posts[-1][1].items())
        assert parse_qs(encoded)["csrfp_token"] == [TOKEN]
