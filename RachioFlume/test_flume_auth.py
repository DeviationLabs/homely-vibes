#!/usr/bin/env python3
"""
Simple test script to debug Flume API authentication.
Usage: python test_flume_auth.py
"""

import sys

sys.path.append("..")

from lib.logger import SystemLogger
from flume_client import FlumeClient

logger = SystemLogger.get_logger(__name__)


def main():
    """Test Flume authentication."""
    logger.info("=== Flume API Authentication Test ===")

    try:
        client = FlumeClient()
        devices = client.get_devices()
        logger.info(f"SUCCESS: Authentication worked! Found {len(devices)} devices")
        for device in devices:
            logger.info(f"  Device: {device.name} (ID: {device.id})")
        return 0

    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
