#!/usr/bin/env python3
import argparse
import os
import sys
import traceback
import time
from lib.config import get_config
from lib.logger import SystemLogger
from lib.FoscamImager import FoscamImager
from lib import Mailer

cfg = get_config()

logger = SystemLogger.get_logger(__name__)
# import TFOneShot ## Imported on demand

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML detector for checking state of garage door")
    parser.add_argument(
        "--always_email",
        help="Send email report",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--out_dir",
        help="Folder for storing output files",
        default="%s/garage_images/" % cfg.paths.home,
    )
    parser.add_argument(
        "--display_image",
        help="Display captured image",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--save_image",
        help="Save images for ML training set",
        action="store_true",
        default=False,
    )
    parser.add_argument("--model_file", help="Trained model", default=None)
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    send_email = args.always_email
    model = None
    msg = ""
    garage_node = cfg.node_check.node_configs["Garage Backup"]
    mycam = FoscamImager(garage_node.ip, args.display_image)

    if args.model_file and os.path.isfile(args.model_file):
        from . import TFOneShot

        (model, model_labels) = TFOneShot.load_my_model(args.model_file)
    while True:
        try:
            currtime = time.localtime()
            ts = time.strftime("%Y-%m-%d_%H-%M-%S", currtime)

            filename = None
            if args.save_image:
                filename = "%s/Garage_%s.jpg" % (args.out_dir, ts)
                print("Saving image to %s" % filename)
            img = mycam.getImage(filename)

            if model is not None:
                label, tmp_msg = TFOneShot.run_predictor(model, model_labels, img)
                logger.info(tmp_msg)
                msg += f"\n{tmp_msg}"
            else:
                # We've already saved the image. don't keep looping
                break

            if currtime.tm_hour == 0 and currtime.tm_min == 0 and send_email:
                Mailer.sendmail(
                    topic="[GarageCheck]",
                    alert=True,
                    message=msg,
                    always_email=send_email,
                )
                send_email = args.always_email
                mycam.reset_errcount()

        except Exception:
            msg += traceback.format_exc()
            logger.error(traceback.format_exc())
            send_email = True

        time.sleep(30)

    logger.info("Done!")
    print("Done!")
