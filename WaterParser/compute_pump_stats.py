#!/usr/bin/env python3
cfg = get_config()
import argparse
import logging
import os
import sys
import traceback
from lib.config import get_config
import Mailer
import PumpReport
import PumpStatsWriter
import TuyaLogParser

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute waterpump stats and email alert")
    parser.add_argument(
        "--always_email",
        help="Send email report",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    logfile = "%s/%s.log" % (cfg.paths.logging_dir, os.path.basename(__file__))
    log_format = "%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s"
    logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
    logging.info("============")
    logging.info("Invoked command: %s" % " ".join(sys.argv))

    try:
        for fileCounter in range(cfg.water_monitor.max_new_files):
            csvLogfile = cfg.paths.tuya_log_base
            csvLogfile += ".{}".format(fileCounter) if fileCounter > 0 else ""
            isMostRecentLog = fileCounter == 0
            csvLog = TuyaLogParser.TuyaLogParser(
                csvLogfile, cfg.paths.json_summary_file, isMostRecentLog
            )

        # Poll data is very coarse. Let's refine using event log.
        PumpStatsWriter.patchWithRachioEvents()

        # Gen Stats for the last N days.
        PumpStatsWriter.writeFromSummary()

        PumpReport.genSendMessage(args.always_email)
    except Exception:
        msg = "Something failed in script execution:\n%s" % traceback.format_exc()
        logging.error(msg)
        Mailer.sendmail(topic="[PumpStats]", alert=True, message=msg, always_email=True)
        raise

    logging.info("Done!")
    print("Done!")
