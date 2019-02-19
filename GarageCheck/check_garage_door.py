#!/usr/bin/env python3.6
import argparse
from foscam.foscam import FoscamCamera, FOSCAM_SUCCESS
import logging
import json
import io
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import os
import sys
import traceback
import time
import Constants
import Mailer
import NetHelpers

def print_ipinfo(returncode, params):
  if returncode != FOSCAM_SUCCESS:
    print('Failed to get IPInfo!')
    return
  print('IP: %s, Mask: %s' % (params['ip'], params['mask']))

#### Main Routine ####
if __name__ == "__main__":
  parser = argparse.ArgumentParser(description = "ML detector for checking state of garage door")
  parser.add_argument('--always_email',
                      help    ='Send email report',
                      action  ='store_true',
                      default =False)
  parser.add_argument('--out_dir',
                      help    ='Folder for storing output files',
                      default ='%s/garage_images/' % Constants.HOME)
  parser.add_argument('--debug_image',
                      help    ='Display captured image',
                      action  ='store_true',
                      default =False)
  parser.add_argument('--save_image',
                      help    ='Save images for ML training set',
                      action  ='store_true',
                      default =False)
  parser.add_argument('--model_file',
                      help    ='Trained model',
                      default =None)
  args = parser.parse_args()

  logfile = '%s/GarageCheck.txt' % Constants.LOGGING_DIR
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  runState = True
  model = None
  msg = None
  mycam = FoscamCamera(Constants.FOSCAM_NODES['Garage'], 88, \
             Constants.FOSCAM_USERNAME, Constants.FOSCAM_PASSWORD)
  if args.debug_image:
    plt.ion()
    plt.tight_layout()
  if args.model_file and os.path.isfile(args.model_file):
    import TFOneShot
    (model, model_labels) = TFOneShot.load_my_model(args.model_file)
  while runState:
    try:
      currtime = time.localtime()
      ts = time.strftime("%Y-%m-%d_%H-%M-%S", currtime)
      if currtime.tm_hour == 0 and currtime.tm_min == 0:
        if send_email:
          Mailer.sendmail(topic="[GarageCheck]", alert=True, message=msg, always_email=send_email)
        send_email = False
        count = 0

      with NetHelpers.no_stdout():
        picture_data = mycam.snap_picture_2()
#       (retVal, IPparams) = mycam.get_ip_info(print_ipinfo)
#       logging.debug("Got IP params: %s" % json.dumps(IPparams))

      if (len(picture_data) < 2 or picture_data[1] is None):
        count += 1
        raise Exception("[%s] No data in image file, or no image returned. Count = %d" % (ts, count))
      imgBytes = picture_data[1]
      img = mpimg.imread(io.BytesIO(imgBytes), format='JPG')

      if args.debug_image == True:
        logging.info("Updating at %s" % ts)
        plt.imshow(img)
        plt.show()
        plt.pause(0.001)

      if args.save_image == True:
        filename = "%s/Garage_%s.jpg" % (args.out_dir, ts)
        with open(filename, "wb") as fh:
          fh.write(imgBytes) ## Ubuntu: Use "eog <filename>" to view
        logging.info("Saved image to %s" % filename)

      if model is not None:
        label, msg = TFOneShot.run_predictor(model, model_labels, img)
        logging.info(msg)

    except Exception as e:
      msg += "Something failed in script execution:\n%s" % traceback.format_exc()
      logging.error(msg)
      send_email = True
    time.sleep(30)

  logging.info('Done!')
  print("Done!")

