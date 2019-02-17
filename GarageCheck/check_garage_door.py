#!/usr/bin/env python3.6
import argparse
from foscam.foscam import FoscamCamera, FOSCAM_SUCCESS
import logging
import json
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
  mycam = FoscamCamera(Constants.FOSCAM_NODES['Garage'], 88, \
             Constants.FOSCAM_USERNAME, Constants.FOSCAM_PASSWORD)
  msg = None
  while runState:
    try:
      currtime = time.localtime()
      if currtime.tm_hour == 0 and currtime.tm_min == 0:
        if send_email:
          Mailer.sendmail(topic="[GarageCheck]", alert=True, message=msg, always_email=send_email)
        send_email = false
        count = 0

      with NetHelpers.no_stdout():
        picture_data = mycam.snap_picture_2()
#       (retVal, IPparams) = mycam.get_ip_info(print_ipinfo)
#       logging.debug("Got IP params: %s" % json.dumps(IPparams))

      if args.save_image == True:
        if (len(picture_data) < 2 or picture_data[1] is None):
          count += 1
          raise Exception("No data in image file, or no image returned. Count = %d" % count)
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", currtime)
        filename = "%s/Garage_%s.jpg" % (args.out_dir, ts)
        fh = open(filename, "wb")
        fh.write(picture_data[1]) ## Ubuntu: Use "eog <filename>" to view
        logging.debug("Saved image to %s" % filename)
        fh.close()
    except Exception as e:
      msg="Something failed in script execution:\n%s" % traceback.format_exc()
      logging.error(msg)
      send_email = true
#      raise
#      runState = False
    time.sleep(30)

  logging.info('Done!')
  print("Done!")

