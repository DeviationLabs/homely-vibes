#!/usr/bin/env python3
"""Test script to get battery status for all August devices."""

import asyncio
from august_client import AugustClient
from lib import Constants
from lib.logger import get_logger

async def test_battery_status():
    """Test battery status reporting for all August devices."""
    logger = get_logger(__name__)
    
    # Initialize client with credentials from Constants
    client = AugustClient(
        email=Constants.AUGUST_EMAIL,
        password=Constants.AUGUST_PASSWORD,
        phone=getattr(Constants, "AUGUST_PHONE", None)
    )
    
    try:
        # Get all lock statuses (includes battery info)
        logger.info("Getting battery status for all August devices...")
        statuses = await client.get_all_lock_statuses()
        
        logger.info(f"Found {len(statuses)} devices with status:")
        for lock_id, status in statuses.items():
            battery_info = f"{status.battery_level}%" if status.battery_level else "Unknown"
            logger.info(f"  🔋 {status.lock_name}: {battery_info}")
            logger.info(f"     Lock Status: {status.lock_status.value}")
            logger.info(f"     Door State: {status.door_state.value}")
            logger.info(f"     Last Update: {status.timestamp}")
            
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_battery_status())