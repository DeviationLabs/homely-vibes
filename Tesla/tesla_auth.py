#!/usr/bin/env python3
"""Tesla Fleet API OAuth helper.

Two modes:
    uv run Tesla/tesla_auth.py                  # OAuth user-token flow
    uv run Tesla/tesla_auth.py --partner-login  # one-time partner_accounts register

The OAuth flow runs a tiny local HTTP server on the configured redirect URI's
port to catch Tesla's redirect, then persists the resulting tokens.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

import aiohttp
from tesla_fleet_api.const import Scope
from tesla_fleet_api.tesla import TeslaFleetOAuth

from lib.config import get_config
from lib.logger import get_logger

logger = get_logger(__name__)

ENERGY_SCOPES = [
    Scope.OPENID,
    Scope.OFFLINE_ACCESS,
    Scope.ENERGY_DEVICE_DATA,
    Scope.ENERGY_CMDS,
]


def _resolve_token_file(token_file: str) -> str:
    token_file = os.path.expanduser(token_file)
    if not os.path.isabs(token_file):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        token_file = os.path.join(project_root, token_file)
    os.makedirs(os.path.dirname(token_file), exist_ok=True)
    return token_file


def _save_tokens(oauth: TeslaFleetOAuth, token_file: str) -> None:
    data = {
        "access_token": oauth._access_token,
        "refresh_token": oauth.refresh_token,
        "expires_at": int(oauth.expires),
        "token_type": "Bearer",
        "created_at": int(time.time()),
    }
    with open(token_file, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(token_file, 0o600)
    logger.info(f"Tokens saved to {token_file}")


class _CallbackHandler(BaseHTTPRequestHandler):
    captured: Dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            _CallbackHandler.captured["code"] = params["code"][0]
            _CallbackHandler.captured["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication received.</h1>"
                b"<p>You can close this window.</p></body></html>"
            )
        else:
            err = params.get("error_description", params.get("error", ["unknown"]))[0]
            _CallbackHandler.captured["error"] = err
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h1>Error: {err}</h1></body></html>".encode())

    def log_message(self, format: str, *args: Any) -> None:  # silence default access log
        pass


def _await_callback(host: str, port: int, timeout_s: int = 300) -> Dict[str, str]:
    _CallbackHandler.captured = {}
    server = HTTPServer((host, port), _CallbackHandler)
    server.timeout = 1
    deadline = time.time() + timeout_s
    while time.time() < deadline and not _CallbackHandler.captured:
        server.handle_request()
    server.server_close()
    return _CallbackHandler.captured


async def _run_oauth_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    region: str,
    token_file: str,
) -> bool:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8585

    async with aiohttp.ClientSession() as session:
        oauth = TeslaFleetOAuth(
            session=session,
            region=region,  # type: ignore[arg-type]
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )

        login_url = oauth.get_login_url(scopes=ENERGY_SCOPES, state="homely-vibes")

        print("\n" + "=" * 70)
        print("TESLA FLEET API AUTHENTICATION")
        print("=" * 70)
        print(f"\n1. Opening browser to authorize at:\n   {login_url}\n")
        print(f"2. Waiting for redirect to {redirect_uri} ...\n")
        try:
            webbrowser.open(login_url)
        except Exception:
            print("   (could not auto-open browser; copy URL manually)")

        result = _await_callback(host, port)

        if "error" in result:
            print(f"\n[FAIL] OAuth error: {result['error']}", file=sys.stderr)
            return False
        if "code" not in result:
            print("\n[FAIL] No auth code received (timeout)", file=sys.stderr)
            return False

        print("Auth code captured. Exchanging for tokens ...")
        await oauth.get_refresh_token(code=result["code"])
        _save_tokens(oauth, token_file)
        print(
            f"\n[OK] Tokens saved. Expires: "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(oauth.expires)))}"
        )
        return True


async def _run_partner_login(
    client_id: str,
    client_secret: str,
    region: str,
    domain: str,
) -> bool:
    async with aiohttp.ClientSession() as session:
        oauth = TeslaFleetOAuth(
            session=session,
            region=region,  # type: ignore[arg-type]
            client_id=client_id,
            client_secret=client_secret,
        )
        print(f"Registering partner account for domain: {domain}")
        result = await oauth.partner_login(
            client_id=client_id,
            client_secret=client_secret,
            scopes=ENERGY_SCOPES,
        )
        access_token = result["access_token"]
        print(f"Got client-credentials token, expires in {result['expires_in']}s.")

        fleet_host = f"https://fleet-api.prd.{region}.vn.cloud.tesla.com"
        async with session.post(
            f"{fleet_host}/api/1/partner_accounts",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"domain": domain},
        ) as resp:
            body = await resp.text()
            print(f"HTTP {resp.status} from /api/1/partner_accounts")
            print(body)
            return resp.status in (200, 201)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tesla Fleet API OAuth helper")
    parser.add_argument(
        "--partner-login",
        action="store_true",
        help="Run one-time partner_accounts registration instead of user OAuth",
    )
    args = parser.parse_args()

    cfg = get_config()
    client_id = cfg.tesla.fleet_client_id
    client_secret = cfg.tesla.fleet_client_secret
    redirect_uri = cfg.tesla.fleet_redirect_uri
    region = cfg.tesla.fleet_region or "na"
    domain = cfg.tesla.fleet_public_key_domain
    token_file = _resolve_token_file(cfg.tesla.tesla_token_file)

    if not client_id or not client_secret:
        print(
            "[FAIL] tesla.fleet_client_id / fleet_client_secret not set in config/local.yaml",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.partner_login:
        ok = asyncio.run(_run_partner_login(client_id, client_secret, region, domain))
    else:
        ok = asyncio.run(
            _run_oauth_flow(client_id, client_secret, redirect_uri, region, token_file)
        )

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
