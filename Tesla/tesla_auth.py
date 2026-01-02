#!/usr/bin/env python3
"""Standalone Tesla OAuth2 authentication using Selenium headless Chrome."""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import undetected_chromedriver as uc
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import requests

from lib import Constants
from lib.logger import get_logger


logger = get_logger(__name__)


class TeslaAuthError(Exception):
    """Authentication failed."""

    pass


def generate_code_verifier() -> str:
    """Generate RFC 7636 compliant code verifier (43-128 chars)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def generate_code_challenge(verifier: str) -> str:
    """Generate SHA256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_url(email: str, code_challenge: str, state: str) -> str:
    """Build OAuth2 authorization URL with PKCE."""
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
    return f"{base_url}?{urlencode(params)}"


def setup_chrome_driver() -> uc.Chrome:
    """Configure and create undetected Chrome driver."""
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    # Use undetected-chromedriver which bypasses bot detection
    driver = uc.Chrome(options=options, use_subprocess=True)

    return driver


def handle_login_flow(
    driver: uc.Chrome, auth_url: str, email: str, password: str, timeout: int = 30
) -> str:
    """Handle Tesla login flow with optional MFA."""
    try:
        logger.info("Navigating to Tesla auth page")
        driver.get(auth_url)

        # Wait for and fill email field
        logger.info("Waiting for email field")
        email_field = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "email"))
        )
        email_field.send_keys(email)

        # Click continue button
        continue_btn = driver.find_element(By.ID, "continue-button")
        continue_btn.click()
        logger.info("Email submitted")

        # Wait for and fill password field
        logger.info("Waiting for password field")
        password_field = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        password_field.send_keys(password)

        # Submit login
        submit_btn = driver.find_element(By.ID, "submit-button")
        submit_btn.click()
        logger.info("Password submitted")

        # Check for MFA
        try:
            logger.info("Checking for MFA prompt")
            mfa_field = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "verification-code"))
            )

            # MFA detected - prompt user
            print("\n" + "=" * 60)
            print("MFA REQUIRED")
            print("=" * 60)
            print("Check your phone/email for a verification code from Tesla.")
            verification_code = input("Enter verification code: ").strip()

            if not verification_code:
                raise TeslaAuthError("No verification code provided")

            mfa_field.send_keys(verification_code)
            verify_btn = driver.find_element(By.ID, "verify-button")
            verify_btn.click()
            logger.info("MFA code submitted")

        except TimeoutException:
            # No MFA required
            logger.info("No MFA required")

        # Wait for redirect to callback URL
        logger.info("Waiting for redirect to callback URL")
        WebDriverWait(driver, timeout).until(lambda d: "void/callback" in d.current_url)
        callback_url = driver.current_url
        logger.info(f"Redirected to callback: {callback_url[:80]}...")

        return callback_url

    except TimeoutException as e:
        screenshot_path = "/tmp/tesla_auth_timeout.png"
        driver.save_screenshot(screenshot_path)
        logger.error(f"Timeout during login - screenshot saved to {screenshot_path}")
        raise TeslaAuthError(f"Login timeout: {e}")

    except NoSuchElementException as e:
        screenshot_path = "/tmp/tesla_auth_element_error.png"
        driver.save_screenshot(screenshot_path)
        logger.error(f"Element not found - screenshot saved to {screenshot_path}")
        raise TeslaAuthError(f"Page layout changed - element not found: {e}")


def extract_authorization_code(callback_url: str, expected_state: str) -> str:
    """Extract and validate authorization code from callback URL."""
    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)

    if "error" in params:
        error = params["error"][0]
        error_desc = params.get("error_description", ["Unknown error"])[0]
        raise TeslaAuthError(f"OAuth error: {error} - {error_desc}")

    if "code" not in params:
        raise TeslaAuthError("No authorization code in callback URL")

    auth_code = params["code"][0]
    state_returned = params.get("state", [None])[0]

    # Validate state (CSRF protection)
    if state_returned != expected_state:
        raise TeslaAuthError("State mismatch - possible CSRF attack")

    logger.info("Authorization code extracted successfully")
    return auth_code


def exchange_code_for_tokens(auth_code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    token_url = "https://auth.tesla.com/oauth2/v3/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": "ownerapi",
        "code": auth_code,
        "code_verifier": code_verifier,
        "redirect_uri": "https://auth.tesla.com/void/callback",
    }

    logger.info("Exchanging authorization code for tokens")

    try:
        response = requests.post(token_url, json=data, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        raise TeslaAuthError(f"Token exchange failed: {e}")

    tokens = response.json()

    if "access_token" not in tokens or "refresh_token" not in tokens:
        raise TeslaAuthError(f"Invalid token response: {tokens}")

    logger.info("Tokens received successfully")
    return tokens


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


def get_credentials() -> Tuple[str, str]:
    """Get credentials from Constants with fallback to env vars."""
    email = os.getenv("TESLA_EMAIL") or getattr(Constants, "TESLA_EMAIL", None)
    password = os.getenv("TESLA_PASSWORD") or getattr(Constants, "TESLA_PASSWORD", None)

    if not email or not password:
        raise ValueError(
            "Tesla credentials not configured in Constants.py or environment variables"
        )

    return email, password


def authenticate_tesla(token_file: str = "~/logs/tesla_tokens.json") -> bool:
    """Complete OAuth2 + PKCE authentication flow."""
    driver: Optional[uc.Chrome] = None

    try:
        # Get credentials
        email, password = get_credentials()
        logger.info(f"Authenticating Tesla account: {email}")

        # Generate PKCE parameters
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = secrets.token_urlsafe(32)

        # Build authorization URL
        auth_url = build_authorization_url(email, code_challenge, state)

        # Setup Chrome driver
        driver = setup_chrome_driver()

        # Handle login flow (with MFA if needed)
        callback_url = handle_login_flow(driver, auth_url, email, password)

        # Extract authorization code
        auth_code = extract_authorization_code(callback_url, state)

        # Exchange code for tokens
        tokens = exchange_code_for_tokens(auth_code, code_verifier)

        # Save tokens
        save_tokens(tokens, token_file)

        print("\n" + "=" * 60)
        print("✓ AUTHENTICATION SUCCESSFUL")
        print("=" * 60)
        print(f"Tokens saved to: {os.path.expanduser(token_file)}")
        print(
            f"Token expires at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(time.time()) + tokens['expires_in']))}"
        )
        print("\nYou can now run Tesla/manage_power.py")
        print("=" * 60)

        return True

    except TeslaAuthError as e:
        logger.error(f"Authentication failed: {e}")
        print(f"\n✗ Authentication failed: {e}", file=sys.stderr)
        return False

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"\n✗ Unexpected error: {e}", file=sys.stderr)
        return False

    finally:
        if driver:
            driver.quit()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Tesla OAuth2 Authentication")
    parser.add_argument(
        "--token-file",
        default="~/logs/tesla_tokens.json",
        help="Path to save tokens (default: ~/logs/tesla_tokens.json)",
    )
    parser.add_argument("--test", action="store_true", help="Test authentication only")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Starting Tesla authentication")
    logger.info("=" * 60)

    success = authenticate_tesla(args.token_file)

    if not success:
        sys.exit(1)

    logger.info("Authentication completed")


if __name__ == "__main__":
    main()
