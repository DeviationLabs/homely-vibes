#!/usr/bin/env python3
"""Reachability probe for the uplink watchdog.

Kept apart from the watchdog itself because this is the one piece that touches
the real network, so tests inject a fake in its place.
"""

import socket

DEFAULT_TIMEOUT_SECS = 4


def probe_internet(targets: list[str], timeout: int = DEFAULT_TIMEOUT_SECS) -> bool:
    """True if any target accepts a TCP connection. Targets are ``ip:port``.

    Deliberately DNS-free. A name-based probe reports a false outage when only
    the Deco's DNS proxy has died -- one of the exact failures we detect -- and
    false health when a captive resolver answers for everything.
    """
    for target in targets:
        host, _, port = target.rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except (OSError, ValueError):
            continue
    return False
