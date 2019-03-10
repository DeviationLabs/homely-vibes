#!/usr/bin/env python3.5
import argparse
import logging
import json
import os
import sys
import traceback
import time
import Constants
import FoscamImager
import Mailer
import NetHelpers

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

  filename = None
  runState = True
  model = None
  msg = ""
  mycam = FoscamImager.FoscamImager(Constants.FOSCAM_NODES['Garage'], args.debug_image)
  if args.model_file and os.path.isfile(args.model_file):
    import TFOneShot
    (model, model_labels) = TFOneShot.load_my_model(args.model_file)
  while runState:
#    try:
      currtime = time.localtime()
      ts = time.strftime("%Y-%m-%d_%H-%M-%S", currtime)
      if currtime.tm_hour == 0 and currtime.tm_min == 0 and send_email:
        Mailer.sendmail(topic="[GarageCheck]", alert=True, message=msg, always_email=send_email)
        send_email = False
        mycam.reset_errcount()

      if args.save_image == True:
        filename = "%s/Garage_%s.jpg" % (args.out_dir, ts)
      img = mycam.getImage(filename)

      if model is not None:
        label, msg = TFOneShot.run_predictor(model, model_labels, img)
        logging.info(msg)

#    except Exception as e:
#      msg += traceback.format_exc()
#      logging.error(traceback.format_exc())
#      send_email = True
#    time.sleep(30)
#
#  logging.info('Done!')
#  print("Done!")

