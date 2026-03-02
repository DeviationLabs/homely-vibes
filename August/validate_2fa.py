#!/usr/bin/env python3
"""Quick script to validate 2FA code for August authentication."""

import asyncio
import os
import aiohttp
from yalexs.authenticator_async import AuthenticatorAsync, AuthenticationState
from yalexs.api_async import ApiAsync
from lib.config import get_config


async def complete_2fa() -> bool:
    cfg = get_config()
    session = aiohttp.ClientSession()
    try:
        api = ApiAsync(session)
        cache_file = cfg.august.token_file
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        auth = AuthenticatorAsync(
            api,
            "email",
            cfg.august.email,
            cfg.august.password,
            access_token_cache_file=cache_file,
        )
        await auth.async_setup_authentication()

        # First authenticate to get into REQUIRES_VALIDATION state
        result = await auth.async_authenticate()
        print(f"Auth state: {result.state}")

        if result.state == AuthenticationState.AUTHENTICATED:
            print("Already authenticated! Testing lock access...")
            locks = await api.async_get_locks(result.access_token)
            print(f"Found {len(locks)} locks:")
            for lock in locks:
                print(f"  - {lock.device_name} ({lock.device_id})")
            print(f"Token cached to: {cache_file}")
            return True

        if result.state != AuthenticationState.REQUIRES_VALIDATION:
            print(f"Unexpected state: {result.state}")
            return False

        # Send verification code
        print("Sending verification code to your phone/email...")
        send_result = await auth.async_send_verification_code()

        if not send_result:
            print("Failed to send verification code")
            return False

        print("Verification code sent! Check your phone/email.")

        import sys

        print("Enter the 6-digit verification code: ", end="", flush=True)
        verification_code = sys.stdin.readline().strip()

        print(f"Validating code: {verification_code}")
        validation_result = await auth.async_validate_verification_code(verification_code)

        print(f"Validation result: {validation_result}")

        from yalexs.authenticator_async import ValidationResult

        if validation_result != ValidationResult.VALIDATED:
            print("Verification code validation failed")
            return False

        print("Verification code validated!")

        print("Getting authenticated session...")
        auth_result = await auth.async_authenticate()
        print(f"Final auth state: {auth_result.state}")

        if auth_result.state != AuthenticationState.AUTHENTICATED:
            print(f"Authentication still not complete: {auth_result.state}")
            return False

        print("Authentication complete!")
        locks = await api.async_get_locks(auth_result.access_token)
        print(f"Found {len(locks)} locks:")
        for lock in locks:
            print(f"  - {lock.device_name} ({lock.device_id})")
        print(f"Token cached to: {cache_file}")
        return True

    finally:
        await session.close()


if __name__ == "__main__":
    success = asyncio.run(complete_2fa())
    print(f"Final result: {'SUCCESS' if success else 'FAILED'}")
