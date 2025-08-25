#!/usr/bin/env python3

import logging
import os
import subprocess
import sys
import urllib.request
from . import Constants
from . import Mailer


#### Main Routine ####
if __name__ == "__main__":
    logfile = "%s/%s.log" % (Constants.LOGGING_DIR, os.path.basename(__file__))
    log_format = "%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s"
    logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
    logging.info("============")
    logging.info("Invoked command: %s" % " ".join(sys.argv))

    IP_PAGE = "http://myip.dnsomatic.com/"
    alert = False
    msg = ""
    try:
        page = urllib.request.urlopen(IP_PAGE)
        msg = page.read().decode("utf-8")
        logging.debug("got %s" % msg)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        msg = e.output
        alert = True
    finally:
        logging.info(msg)

    Mailer.sendmail(topic="[Eden's IP]", message=msg, always_email=True, alert=alert)
