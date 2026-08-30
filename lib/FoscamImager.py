#!/usr/bin/env python3
from libpyfoscam.foscam import FoscamCamera, FOSCAM_SUCCESS
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import io
import logging
import time
from lib.config import get_config
from lib import NetHelpers


def print_ipinfo(returncode, params):
    if returncode != FOSCAM_SUCCESS:
        print("Failed to get IPInfo!")
        return
    print("IP: %s, Mask: %s" % (params["ip"], params["mask"]))


class FoscamImager:
    def __init__(self, nodeIP, display_images=False):
        cfg = get_config()
        self.nodeIP = nodeIP
        self.mycam = FoscamCamera(
            nodeIP, 88, cfg.node_check.foscam.username, cfg.node_check.foscam.password
        )
        self.display_images = display_images
        self.err_count = 0
        if display_images:
            plt.ion()
            plt.tight_layout()

    def reset_errcount(self):
        self.err_count = 0

    def getImageBytes(self):
        with NetHelpers.no_stdout():
            picture_data = self.mycam.snap_picture_2()
        #     (retVal, IPparams) = self.mycam.get_ip_info(print_ipinfo)
        #     logging.debug("Got IP params: %s" % json.dumps(IPparams))

        if len(picture_data) < 2 or picture_data[1] is None:
            self.err_count += 1
            logging.error(f"Bad image from {self.nodeIP}. Count = {self.err_count}")
            return None
        imgBytes = picture_data[1]
        return imgBytes

    def getImage(self, filename=None):
        currtime = time.localtime()
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", currtime)
        logging.debug("Updating at %s" % ts)

        imgBytes = self.getImageBytes()
        img = mpimg.imread(io.BytesIO(imgBytes), format="JPG")
        if filename is not None:
            with open(filename, "wb") as fh:
                fh.write(imgBytes)  ## Ubuntu: Use "eog <filename>" to view
            logging.debug("Saved image to %s" % filename)
        if self.display_images:
            plt.imshow(img)
            plt.show()
            plt.pause(0.001)
        return img
