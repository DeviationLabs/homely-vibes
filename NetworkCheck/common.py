#!/usr/bin/env python3
"""Shared wiring for the NetworkCheck scripts.

Every entry point in this module needs the same two things: a Pushover client
bound to the NetworkCheck app token, and a start-of-run banner in the log. Both
were copy-pasted into each script, which meant three places to keep in sync and
three chances to bind the wrong token.
"""

import logging
import sys

from lib.config import get_config
from lib.MyPushover import Pushover

BANNER = "=" * 50


def network_notifier() -> Pushover:
    """Pushover client bound to the NetworkCheck app token."""
    cfg = get_config()
    return Pushover(cfg.pushover.user, cfg.pushover.tokens["NetworkCheck"])


def log_invocation(logger: logging.Logger) -> None:
    """Record how the script was invoked.

    Cron redirects stdout+stderr to a file, but that only catches crashes; this
    is what tells you *which* invocation produced the lines that follow.
    """
    logger.info(BANNER)
    logger.info("Invoked: %s", " ".join(sys.argv))
