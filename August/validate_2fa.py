#!/usr/bin/env python3
"""Quick script to validate 2FA code for August authentication."""

import asyncio
import aiohttp
from yalexs.authenticator_async import AuthenticatorAsync, AuthenticationState
from yalexs.api_async import ApiAsync
from lib import Constants


async def complete_2fa():
    session = aiohttp.ClientSession()
    try:
        api = ApiAsync(session)
        cache_file = f"{Constants.LOGGING_DIR}/august_auth_token.json"
        auth = AuthenticatorAsync(
            api,
            "email",
            Constants.AUGUST_EMAIL,
            Constants.AUGUST_PASSWORD,
            access_token_cache_file=cache_file,
        )
        await auth.async_setup_authentication()

        # First authenticate to get into REQUIRES_VALIDATION state
        result = await auth.async_authenticate()
        print(f"Auth state: {result.state}")

        if result.state == AuthenticationState.REQUIRES_VALIDATION:
            # First, send verification code
            print("Sending verification code to your phone/email...")
            send_result = await auth.async_send_verification_code()

            if not send_result:
                print("❌ Failed to send verification code")
                return False

            print("✅ Verification code sent!")
            print("📱 Check your phone for SMS or email for verification code")

            import sys

            print("Enter the 6-digit verification code: ", end="", flush=True)
            verification_code = sys.stdin.readline().strip()

            print(f"Validating code: {verification_code}")
            validation_result = await auth.async_validate_verification_code(verification_code)

            print(f"Validation result: {validation_result}")

            # Import ValidationResult to check the result
            from yalexs.authenticator_async import ValidationResult

            if validation_result == ValidationResult.VALIDATED:
                print("✅ Verification code validated!")

                # Now authenticate again to get the full access token
                print("Getting authenticated session...")
                auth_result = await auth.async_authenticate()
                print(f"Final auth state: {auth_result.state}")

                if auth_result.state == AuthenticationState.AUTHENTICATED:
                    print("🎉 SUCCESS! Authentication complete!")

                    # Test if we can get locks now
                    print("Testing lock access...")
                    locks = await api.async_get_locks(auth_result.access_token)
                    print(f"Found {len(locks)} locks:")
                    for lock in locks:
                        print(f"  - {lock.device_name} ({lock.device_id})")

                    # Save the token for future use
                    print(f"Token cached to: {cache_file}")
                    return True
                else:
                    print(f"❌ Authentication still not complete: {auth_result.state}")
                    return False
            else:
                print("❌ Verification code validation failed")
                return False
        else:
            print(f"Unexpected state: {result.state}")
            return False

    finally:
        await session.close()


if __name__ == "__main__":
    success = asyncio.run(complete_2fa())
    print(f"Final result: {'SUCCESS' if success else 'FAILED'}")
