#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from lib.logger import SystemLogger
from lib import Mailer

logger = SystemLogger.get_logger(__name__)

#### Main Routine ####
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge Foscam videos from NAS")
    parser.add_argument(
        "--always_email", help="Send email report", action="store_true", default=False
    )
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    script_dir = os.path.dirname(os.path.realpath(__file__))
    cmd = "%s/purge_old_foscam_files.sh" % script_dir
    alert = False
    try:
        msg = subprocess.check_output(
            cmd.split(),
            stderr=subprocess.STDOUT,
            shell=True,
            universal_newlines=True,
            timeout=600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        msg = e.output
        alert = True
    finally:
        logger.info(msg)

    Mailer.sendmail(
        topic="[PurgeFoscam]", alert=alert, message=msg, always_email=args.always_email
    )
    print("Done!")
