#!/usr/bin/env python3
"""
Simple token extractor for HAR files.
Extracts access_token and id_token from LogRocket HAR files.
"""

import json
import re
import click
import base64
from typing import Optional


def decode_jwt_payload(token: str) -> Optional[dict]:
    """Decode JWT payload"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload (base64url)
        payload = parts[1]
        padding = "=" * (4 - (len(payload) % 4)) if len(payload) % 4 != 0 else ""
        payload += padding
        payload_bytes = base64.urlsafe_b64decode(payload)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None


def analyze_jwe_token(token: str) -> dict:
    """Analyze JWE (JSON Web Encryption) token structure"""
    try:
        parts = token.split(".")
        if len(parts) == 5:
            header, encrypted_key, iv, ciphertext, tag = parts

            # Decode header
            padding = "=" * (4 - (len(header) % 4)) if len(header) % 4 != 0 else ""
            header += padding
            header_bytes = base64.urlsafe_b64decode(header)
            header_json = json.loads(header_bytes.decode("utf-8"))

            return {
                "type": "JWE (JSON Web Encryption)",
                "header": header_json,
                "encrypted_key_length": len(encrypted_key),
                "iv_length": len(iv),
                "ciphertext_length": len(ciphertext),
                "tag_length": len(tag),
                "note": "This is encrypted content that requires decryption with the appropriate key",
            }
    except Exception as e:
        return {"error": f"Failed to analyze JWE: {e}"}

    return {"type": "Unknown token format"}


@click.command()
@click.argument("har_file_path", type=click.Path(exists=True))
@click.option("--decode-jwt", "-d", is_flag=True, help="Decode JWT payload information")
def main(har_file_path: str, decode_jwt: bool):
    """Extract tokens from LogRocket HAR file."""

    print(f"🔍 Analyzing HAR file: {har_file_path}")

    # Read the entire file as text for pattern matching
    with open(har_file_path, "r", encoding="utf-8") as f:
        har_content = f.read()

    # Extract access tokens
    access_token_pattern = r'access_token=([^&\s"\']+)'
    access_tokens = list(set(re.findall(access_token_pattern, har_content)))

    # Extract id tokens
    id_token_pattern = r'id_token=([^&\s"\']+)'
    id_tokens = list(set(re.findall(id_token_pattern, har_content)))

    # Extract bearer tokens from Authorization headers
    bearer_pattern = r'"Authorization"[^"]*"Bearer\s+([^"]+)"'
    bearer_tokens = list(set(re.findall(bearer_pattern, har_content)))

    # Extract refresh/renew tokens
    refresh_patterns = [
        r'refresh_token=([^&\s"\']+)',
        r'renew_token=([^&\s"\']+)',
        r'"refresh_token":\s*"([^"]+)"',
        r'"renew_token":\s*"([^"]+)"',
    ]

    refresh_tokens = []
    for pattern in refresh_patterns:
        refresh_tokens.extend(re.findall(pattern, har_content))
    refresh_tokens = list(set(refresh_tokens))

    print("📊 Token extraction complete")

    # Display results
    if access_tokens:
        print(f"\n🎫 Found {len(access_tokens)} Access Token(s):")
        for i, token in enumerate(access_tokens, 1):
            print(f"  {i}. {token[:50]}...")

            if decode_jwt:
                # Analyze token structure
                if "." in token and len(token.split(".")) == 5:
                    # This looks like a JWE token
                    analysis = analyze_jwe_token(token)
                    print(f"     Analysis: {json.dumps(analysis, indent=6)}")
                else:
                    # Try regular JWT decoding
                    payload = decode_jwt_payload(token)
                    if payload:
                        print(f"     JWT Payload: {json.dumps(payload, indent=6)}")
                    else:
                        print("     Note: Could not decode as standard JWT")
            print()

    if id_tokens:
        print(f"\n🆔 Found {len(id_tokens)} ID Token(s):")
        for i, token in enumerate(id_tokens, 1):
            print(f"  {i}. {token[:50]}...")

            if decode_jwt:
                payload = decode_jwt_payload(token)
                if payload:
                    print(f"     JWT Payload: {json.dumps(payload, indent=6)}")
            print()

    if bearer_tokens:
        print(f"\n🔑 Found {len(bearer_tokens)} Bearer Token(s) from Headers:")
        for i, token in enumerate(bearer_tokens, 1):
            print(f"  {i}. {token[:50]}...")

            if decode_jwt:
                payload = decode_jwt_payload(token)
                if payload:
                    print(f"     JWT Payload: {json.dumps(payload, indent=6)}")
            print()

    if refresh_tokens:
        print(f"\n🔄 Found {len(refresh_tokens)} Refresh/Renew Token(s):")
        for i, token in enumerate(refresh_tokens, 1):
            print(f"  {i}. {token[:50]}...")

            if decode_jwt:
                payload = decode_jwt_payload(token)
                if payload:
                    print(f"     JWT Payload: {json.dumps(payload, indent=6)}")
            print()

    # Summary for easy copying
    print("\n" + "=" * 50)
    print("SUMMARY FOR COPYING:")
    print("=" * 50)

    if access_tokens:
        print("\n# ACCESS TOKENS:")
        for token in access_tokens:
            print(f"ACCESS_TOKEN={token}")

    if id_tokens:
        print("\n# ID TOKENS:")
        for token in id_tokens:
            print(f"ID_TOKEN={token}")

    if bearer_tokens:
        print("\n# BEARER TOKENS:")
        for token in bearer_tokens:
            print(f"BEARER_TOKEN={token}")

    if refresh_tokens:
        print("\n# REFRESH TOKENS:")
        for token in refresh_tokens:
            print(f"REFRESH_TOKEN={token}")

    if not (access_tokens or id_tokens or bearer_tokens or refresh_tokens):
        print("❌ No tokens found in the HAR file.")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
