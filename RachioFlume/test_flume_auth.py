#!/usr/bin/env python3
"""
Simple test script to debug Flume API authentication.
Usage: python test_flume_auth.py
"""

import os
import sys
sys.path.append('..')

from lib.logger import SystemLogger
from flume_client import FlumeClient

logger = SystemLogger.get_logger(__name__)

def main():
    """Test Flume authentication with detailed debugging."""
    logger.info("=== Flume API Authentication Test ===")
    
    # Test credential configuration
    try:
        client = FlumeClient()
        
        # Test credential validation
        cred_test = client.test_credentials()
        logger.info("Credential validation results:")
        for key, value in cred_test.items():
            logger.info(f"  {key}: {value}")
        
        if not cred_test["all_credentials_present"]:
            logger.error("Missing credentials - cannot proceed with API test")
            logger.info("Required environment variables:")
            logger.info("  - FLUME_CLIENT_ID")
            logger.info("  - FLUME_CLIENT_SECRET") 
            logger.info("  - FLUME_USER_EMAIL")
            logger.info("  - FLUME_PASSWORD")
            return 1
            
        # Test API authentication
        logger.info("Testing API authentication...")
        try:
            devices = client.get_devices()
            logger.info(f"SUCCESS: Authentication worked! Found {len(devices)} devices")
            for device in devices:
                logger.info(f"  Device: {device.name} (ID: {device.id})")
            return 0
            
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return 1
            
    except Exception as e:
        logger.error(f"Error creating Flume client: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())