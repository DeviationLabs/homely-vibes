#!/usr/bin/env python3
"""Xfinity gateway local admin client -- reboot only.

The upstream modem is the second lever the watchdog can pull. It is bridged
here, so the Deco holds the public IP and this box's management interface sits
one hop past it; reaching it therefore depends on the Deco still routing, which
is why a failure to reach it is never fatal (see `UplinkWatchdog._execute`).

Protocol, read off the live device rather than guessed (see the README's
"Rebooting the modem" section for the recon transcript):

1. ``POST /check.jst`` with ``username`` / ``password`` -> sets ``DUKSID`` and
   ``csrfp_token`` cookies and redirects to ``at_a_glance.jst``.
2. ``GET /restore_reboot.jst`` -> the page embeds a per-session CSRF token as
   ``var token = "...."``. The cookie of the same name is *not* what the
   handler validates; the scraped value is.
3. ``POST actionHandler/ajaxSet_Reset_Restore.jst`` with
   ``resetInfo=["<button>","<scope>","admin"]`` and ``csrfp_token``.
   Replies with JSON; ``{"reboot": true}`` means it accepted.

DANGER -- read before touching `_REBOOT_BUTTON`:

    btn1  "Reset the Gateway"                            -> Device            REBOOT
    btn2  "Reset Wi-Fi Module"                           -> Wifi
    btn3  "Reset the Wi-Fi Gateway"                      -> Wifi,Router
    btn4  "Restore manufacturer defaults for Wi-Fi Only" -> Wifi              DESTRUCTIVE
    btn5  "Restore Factory settings"                     -> Router,Wifi,...   DESTRUCTIVE
    btn6  "Reset Password"                               -> password         DESTRUCTIVE

The reboot we want is one identifier away from a full factory wipe on the same
endpoint with the same payload shape. That is why the button is a module
constant and `reboot()` takes no arguments: there is deliberately no parameter
anyone could thread a different value through, and no code path that builds the
id dynamically.
"""

import json
import re
from typing import Any, Optional

import requests

from lib.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TIMEOUT = 15

# See the DANGER block above. Never parameterize these two.
_REBOOT_BUTTON = "btn1"
_REBOOT_SCOPE = "Device"
# ...and never send them without confirming the device still agrees on what
# they mean. The ids belong to the gateway's firmware, not to us, and Comcast
# pushes updates unattended: a unit test can pin the bytes we emit, but only a
# runtime check can catch a firmware that renumbered the buttons underneath us.
_REBOOT_TITLE = "reset the gateway"

# The page renders its CSRF token into a script literal.
_TOKEN_RE = re.compile(r'var\s+token\s*=\s*"([^"]+)"')
# A bounced session re-serves the login form rather than returning 401.
_LOGIN_FORM = 'action="check.jst"'


def _scrape_token(page: str) -> str:
    """The per-session CSRF token the reset handler validates.

    Note it is the value rendered into the page, not the cookie of the same
    name -- sending the cookie's value is rejected.
    """
    match = _TOKEN_RE.search(page)
    if not match:
        raise ModemAPIError("Gateway reboot page carried no CSRF token")
    return match.group(1)


def _verify_reboot_button(page: str) -> None:
    """Refuse unless the device still labels our button as the reboot.

    This is the guard that a unit test cannot provide. Pinning the payload
    proves what we transmit; it says nothing about what the firmware now does
    with it, and the neighbouring id on this same endpoint is a factory wipe.
    So the *semantic* label is checked at runtime, immediately before the POST:
    positional agreement is not enough when the position belongs to somebody
    else's firmware.

    Failing here is the safe outcome -- the watchdog logs it and goes on to
    reboot the Deco, which is the lever that actually matters.
    """
    for tag in re.findall(r"<a\b[^>]*>", page, re.I):
        if not re.search(rf'id=["\']{_REBOOT_BUTTON}["\']', tag, re.I):
            continue
        found = re.search(r'title=["\']([^"\']*)["\']', tag, re.I)
        label = (found.group(1) if found else "").strip().lower()
        if label != _REBOOT_TITLE:
            raise ModemAPIError(
                f"{_REBOOT_BUTTON} is now labelled {label!r}, expected {_REBOOT_TITLE!r}; "
                "refusing to POST a reset whose meaning may have changed"
            )
        return
    raise ModemAPIError(f"{_REBOOT_BUTTON} is absent from the reset page; refusing to POST")


class ModemAuthError(Exception):
    """Gateway admin login failed, or the session was rejected."""


class ModemAPIError(Exception):
    """Gateway admin UI was unreachable or answered with something unusable."""


class ModemClient:
    """Local-UI client for the upstream Xfinity gateway. Reboot only."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: Optional[requests.Session] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.session = session or requests.Session()
        self.timeout = timeout

    def verify(self) -> str:
        """Read-only credential and button check. Never POSTs.

        Runs every step of `reboot()` except the final POST -- by construction,
        via the same `_prepare()`, so the check cannot silently drift from the
        thing it is checking. That matters more here than for the Deco: the
        modem stage fires rarely, and its nastiest failure (a firmware that
        renumbered the reset buttons) is invisible until the moment it is
        needed.
        """
        self._prepare()
        return f"{_REBOOT_BUTTON} present and labelled {_REBOOT_TITLE!r}"

    def reboot(self) -> None:
        """Log in and restart the gateway. Takes ~4 minutes to come back.

        Takes no arguments on purpose -- see the DANGER block at the top of
        this module.
        """
        token = self._prepare()
        payload = json.dumps([_REBOOT_BUTTON, _REBOOT_SCOPE, "admin"])
        body = self._post(
            "/actionHandler/ajaxSet_Reset_Restore.jst",
            {"resetInfo": payload, "csrfp_token": token},
        )

        try:
            accepted = bool(json.loads(body).get("reboot"))
        except ValueError as err:
            raise ModemAPIError(f"Gateway reboot reply was not JSON: {body[:120]}") from err
        if not accepted:
            # The handler answers 200 with {"reboot": false} when it declines
            # (wrong scope, stale token). Treating that as success would let
            # the watchdog log a reboot that never happened.
            raise ModemAPIError(f"Gateway declined the reboot: {body[:120]}")
        logger.info("Gateway reboot issued; expect ~4 minutes before it is back")

    def _prepare(self) -> str:
        """Everything `reboot()` does short of the POST; returns the token.

        Shared with `verify()` on purpose, so the daily check exercises the
        exact path the emergency will take.
        """
        self._login()
        page = self._reboot_page()
        _verify_reboot_button(page)
        return _scrape_token(page)

    def _login(self) -> None:
        self._post("/check.jst", {"username": self.username, "password": self.password})
        if "DUKSID" not in self.session.cookies:
            raise ModemAuthError("Gateway login did not set a session cookie")

    def _reboot_page(self) -> str:
        """Fetch the reset page -- source of both the token and the guard."""
        try:
            response = self.session.get(
                f"{self.host}/restore_reboot.jst",
                timeout=self.timeout,
                headers={"Referer": f"{self.host}/"},
            )
            response.raise_for_status()
        except requests.RequestException as err:
            raise ModemAPIError(f"Gateway reboot page unreachable: {err}") from err

        if _LOGIN_FORM in response.text:
            raise ModemAuthError("Gateway bounced us back to the login form")
        return str(response.text)

    def _post(self, path: str, data: dict[str, Any]) -> str:
        try:
            response = self.session.post(
                f"{self.host}{path}",
                data=data,
                headers={"Referer": f"{self.host}/"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return str(response.text)
        except requests.RequestException as err:
            raise ModemAPIError(f"Gateway request to {path} failed: {err}") from err
