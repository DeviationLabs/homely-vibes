#!/usr/bin/env python3
"""Manual Tesla OAuth helper - for when hCaptcha blocks automation."""

import base64
import hashlib
import json
import os
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from lib import Constants
from lib.logger import get_logger

logger = get_logger(__name__)


def generate_code_verifier() -> str:
    """Generate RFC 7636 compliant code verifier."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def generate_code_challenge(verifier: str) -> str:
    """Generate SHA256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def save_tokens(tokens: dict, token_file: str) -> None:
    """Save tokens to file with proper permissions."""
    token_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": int(time.time()) + tokens["expires_in"],
        "token_type": tokens["token_type"],
        "created_at": int(time.time()),
    }

    token_file = os.path.expanduser(token_file)
    os.makedirs(os.path.dirname(token_file), exist_ok=True)

    with open(token_file, "w") as f:
        json.dump(token_data, f, indent=2)

    os.chmod(token_file, 0o600)
    logger.info(f"Tokens saved to {token_file}")


def manual_auth_flow(email: str, token_file: str = "~/logs/tesla_tokens.json") -> bool:
    """Manual OAuth flow - user completes auth in their own browser."""
    # Generate PKCE parameters
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(32)

    # Build authorization URL
    base_url = "https://auth.tesla.com/oauth2/v3/authorize"
    params = {
        "client_id": "ownerapi",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": "https://auth.tesla.com/void/callback",
        "response_type": "code",
        "scope": "openid email offline_access",
        "state": state,
        "login_hint": email,
    }
    auth_url = f"{base_url}?{urlencode(params)}"

    print("\n" + "=" * 70)
    print("MANUAL TESLA AUTHENTICATION")
    print("=" * 70)
    print("\nTesla blocks automated browsers with hCaptcha.")
    print("You need to complete authentication manually in your regular browser.\n")
    print("STEP 1: Open this URL in your browser (regular Chrome/Safari/Firefox):")
    print("-" * 70)
    print(auth_url)
    print("-" * 70)
    print("\nSTEP 2: Complete login (email, password, MFA if required)")
    print("STEP 3: Solve hCaptcha")
    print("STEP 4: After success, you'll be redirected to:")
    print("        https://auth.tesla.com/void/callback?code=...")
    print("\nSTEP 5: Copy the ENTIRE callback URL and paste it here.\n")

    # Get callback URL from user
    callback_url = input("Paste callback URL: ").strip()

    if not callback_url or "void/callback" not in callback_url:
        print("\n✗ Invalid URL - must contain 'void/callback'", file=sys.stderr)
        return False

    # Parse authorization code
    try:
        parsed = urlparse(callback_url)
        params = parse_qs(parsed.query)

        if "error" in params:
            error = params["error"][0]
            error_desc = params.get("error_description", ["Unknown"])[0]
            print(f"\n✗ OAuth error: {error} - {error_desc}", file=sys.stderr)
            return False

        if "code" not in params:
            print("\n✗ No authorization code found in URL", file=sys.stderr)
            return False

        auth_code = params["code"][0]
        state_returned = params.get("state", [None])[0]

        # Validate state
        if state_returned != state:
            print("\n✗ State mismatch - possible security issue", file=sys.stderr)
            return False

        print("\n✓ Authorization code extracted")

    except Exception as e:
        print(f"\n✗ Failed to parse URL: {e}", file=sys.stderr)
        return False

    # Exchange code for tokens
    print("Exchanging code for tokens...")
    token_url = "https://auth.tesla.com/oauth2/v3/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": "ownerapi",
        "code": auth_code,
        "code_verifier": code_verifier,
        "redirect_uri": "https://auth.tesla.com/void/callback",
    }

    try:
        response = requests.post(token_url, json=data, timeout=10)
        response.raise_for_status()
        tokens = response.json()

        if "access_token" not in tokens or "refresh_token" not in tokens:
            print(f"\n✗ Invalid token response: {tokens}", file=sys.stderr)
            return False

        # Save tokens
        save_tokens(tokens, token_file)

        print("\n" + "=" * 70)
        print("✓ AUTHENTICATION SUCCESSFUL")
        print("=" * 70)
        print(f"Tokens saved to: {os.path.expanduser(token_file)}")
        print(f"Expires: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(time.time()) + tokens['expires_in']))}")
        print("\nYou can now run: python Tesla/manage_power.py")
        print("=" * 70)

        return True

    except requests.RequestException as e:
        print(f"\n✗ Token exchange failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    """Main entry point."""
    email = os.getenv("TESLA_EMAIL") or getattr(Constants, "TESLA_EMAIL", None)

    if not email:
        print("✗ TESLA_EMAIL not configured in Constants.py", file=sys.stderr)
        sys.exit(1)

    print(f"Authenticating for: {email}")

    success = manual_auth_flow(email)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
