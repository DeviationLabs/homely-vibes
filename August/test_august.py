#!/usr/bin/env python3

import asyncio
from august_client import AugustClient
from lib import Constants

async def test_battery_status():
    client = AugustClient(Constants.AUGUST_EMAIL, Constants.AUGUST_PASSWORD)
    try:
        statuses = await client.get_all_lock_statuses()
        for lock_id, status in statuses.items():
            print(f"{status.lock_name}: {status.battery_level}%")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_battery_status())
