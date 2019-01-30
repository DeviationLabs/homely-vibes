#!/usr/bin/env python3.6
import argparse
from foscam.foscam import FoscamCamera, FOSCAM_SUCCESS
import logging
import json
import sys
import time
import Constants
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
  parser.add_argument('--save_image',
                      help    ='Save images for ML training set',
                      action  ='store_true',
                      default =False)
  parser.add_argument('--alert',
                      help    ='Run ML and report on state',
                      action  ='store_false',
                      default =True)
  args = parser.parse_args()

  logfile = '%s/Junk/check_garage_door.txt' % Constants.HOME
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.DEBUG)
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  runState = True
  while runState:
    try:
      mycam = FoscamCamera(Constants.FOSCAM_NODES['Garage'], 88, \
                         Constants.FOSCAM_USERNAME, Constants.FOSCAM_PASSWORD)

      with NetHelpers.no_stdout():
        (retVal, IPparams) = mycam.get_ip_info(print_ipinfo)
        picture_data = mycam.snap_picture_2()
      logging.debug("Got IP params: %s" % json.dumps(IPparams))

      if args.save_image == True:
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        filename = "%s/Garage_%s.jpg" % (args.out_dir, ts)
        fh = open(filename, "wb")
        fh.write(picture_data[1]) ## Ubuntu: Use "eog <filename>" to view
        logging.debug("Saved image to %s" % filename)
        fh.close()
    except Exception as e:
      msg="Something failed in script execution:\n%s" % traceback.format_exc()
      logging.error(msg)
      Mailer.sendmail(topic="[GarageCheck]", alert=True, message=msg, always_email=True)
      raise
      runState = False
    time.sleep(30)

  logging.info('Done!')
  print("Done!")

