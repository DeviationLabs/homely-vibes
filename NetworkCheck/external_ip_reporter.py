#!/usr/bin/env python3
"""
External IP Address Reporter

Fetches and reports the current external IP address via email and pushover notifications.
Useful for monitoring IP changes when using dynamic IP addresses.
"""

import sys
import urllib.request
import urllib.error
from typing import Tuple
from lib.MyPushover import Pushover
from lib import Mailer
from lib.logger import SystemLogger
from lib import Constants

logger = SystemLogger.get_logger(__name__)
pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS['NetworkCheck'])


def get_external_ip() -> Tuple[str, bool]:
    """
    Fetch the external IP address from DNS-O-Matic service.
    
    Returns:
        Tuple of (ip_address, is_error)
    """
    IP_SERVICES = [
        "http://myip.dnsomatic.com/",
        "http://ipv4.icanhazip.com/",
        "https://api.ipify.org/"
    ]
    
    for service in IP_SERVICES:
        try:
            logger.debug(f"Trying IP service: {service}")
            with urllib.request.urlopen(service, timeout=10) as response:
                ip_address = response.read().decode("utf-8").strip()
                logger.debug(f"Got IP: {ip_address}")
                return ip_address, False
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning(f"Failed to get IP from {service}: {e}")
            continue
    
    # If all services failed
    return "Failed to retrieve external IP from all services", True


def main() -> None:
    """Main entry point."""
    
    logger.info("=" * 50)
    logger.info(f"Started: {' '.join(sys.argv)}")
    
    ip_address, is_error = get_external_ip()
    
    if is_error:
        logger.error(f"IP fetch failed: {ip_address}")
    else:
        logger.info(f"Current external IP: {ip_address}")
    
    # Send notifications
    title = "Eden External IP Address"
    
    Mailer.sendmail(
        topic=f"[{title}]", 
        message=ip_address, 
        always_email=True,
        alert=is_error
    )
    
    pushover.send_message(ip_address, title=title)


if __name__ == "__main__":
    main()
