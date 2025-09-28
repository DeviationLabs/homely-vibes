#!/usr/bin/env python3

import asyncio
from august_client import AugustClient
from lib import Constants
from lib.MyPushover import Pushover

pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["August"])

async def test_battery_status():
    client = AugustClient(Constants.AUGUST_EMAIL, Constants.AUGUST_PASSWORD)
    message = ""
    try:
        statuses = await client.get_all_lock_statuses()
        for _, status in statuses.items():
            message += f"{status.lock_name}: {status.battery_level}%\n"
        pushover.send_message(message, title="August Battery Status", priority=0)
    except Exception as e:
        pushover.send_message(f"Error initializing August client: {e}", title="August Battery Status", priority=2)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_battery_status())
