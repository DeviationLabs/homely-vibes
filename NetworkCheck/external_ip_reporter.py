#!/usr/bin/env python3
"""
External IP Address Reporter

Fetches and reports the current external IP address via email and pushover notifications.
Useful for monitoring IP changes when using dynamic IP addresses.
"""

import requests
from typing import Tuple
from lib import Mailer
from lib.logger import SystemLogger
from NetworkCheck.common import log_invocation, network_notifier

logger = SystemLogger.get_logger(__name__)
pushover = network_notifier()


def get_external_ip() -> Tuple[str, bool]:
    """
    Fetch the external IP address from DNS-O-Matic service.

    Returns:
        Tuple of (ip_address, is_error)
    """
    IP_SERVICES = [
        "https://api.ipify.org/",
        "https://ipv4.icanhazip.com/",
        "https://checkip.amazonaws.com/",
    ]

    for service in IP_SERVICES:
        try:
            logger.debug(f"Trying IP service: {service}")
            response = requests.get(service, timeout=10)
            response.raise_for_status()
            ip_address = response.text.strip()
            logger.debug(f"Got IP: {ip_address}")
            return ip_address, False
        except (requests.RequestException, TimeoutError) as e:
            logger.warning(f"Failed to get IP from {service}: {e}")
            continue

    # If all services failed
    return "Failed to retrieve external IP from all services", True


def main() -> None:
    """Main entry point."""

    log_invocation(logger)

    ip_address, is_error = get_external_ip()

    if is_error:
        logger.error(f"IP fetch failed: {ip_address}")
    else:
        logger.info(f"Current external IP: {ip_address}")

    # Send notifications
    title = "External IP Address"

    Mailer.sendmail(
        topic=f"[{title}]",
        message=ip_address,
        always_email=True,
        alert=is_error,
    )

    pushover.send_message(ip_address, title=title, priority=-1)


if __name__ == "__main__":
    main()
