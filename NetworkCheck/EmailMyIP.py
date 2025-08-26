#!/usr/bin/env python3

import os
import subprocess
import sys
import urllib.request
from lib import Constants
from lib import Mailer
from lib.logger import SystemLogger

logger = SystemLogger.get_logger(__name__)


#### Main Routine ####
if __name__ == "__main__":
    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    IP_PAGE = "http://myip.dnsomatic.com/"
    alert = False
    msg = ""
    try:
        page = urllib.request.urlopen(IP_PAGE)
        msg = page.read().decode("utf-8")
        logger.debug("got %s" % msg)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        msg = e.output
        alert = True
    finally:
        logger.info(msg)

    Mailer.sendmail(topic="[Eden's IP]", message=msg, always_email=True, alert=alert)
