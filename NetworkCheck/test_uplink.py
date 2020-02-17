#!/usr/bin/env python3.5

import json
import logging
import os
import subprocess
import sys
import Constants
import Mailer


#### Main Routine ####
if __name__ == "__main__":
  logfile = '%s/%s.log' % (Constants.LOGGING_DIR, os.path.basename(__file__))
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  msg=""
  cmd = "/usr/bin/speedtest -f json"
  alert = False
  try:
    out = subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT, shell=False,
        universal_newlines=True, timeout=600)
    payload = json.loads(out)
    dlW_mbps = payload.get("download", {}).get("bandwidth", 0)*8/1024/1024
    ulW_mbps = payload.get("upload", {}).get("bandwidth", 0)*8/1024/1024
    ext_ip = payload.get("interface", {}).get("externalIp", "UNK")
    if (dlW_mbps > Constants.MIN_DL_BW and ulW_mbps > Constants.MIN_UL_BW):
        msg = "Link good "
    else:
        msg = "Error: Failed processing output %s\n" % out
        alert = True
    msg += "[%s] DL: %.1f Mbps UL: %.1f Mbps" % (ext_ip, dlW_mbps, ulW_mbps)
  except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
    msg = e.output
    alert = True
  finally:
    logging.info(msg)

  Mailer.sendmail(topic="[SpeedTest]", message=msg, always_email=True, alert=alert)
  print(msg)
  print("Done")

