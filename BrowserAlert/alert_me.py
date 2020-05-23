#!/usr/bin/env python3.6
import argparse
import logging
import os
import re
import sys
import time
from tld import get_tld
import Constants
import Mailer
import MyTwilio
import NetHelpers

records = {}
parse_start_time = 0


def refresh_dns_cache():
  # Purge DNS cache before start of tailer...
  cmd = "sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder && date"
  return NetHelpers.ssh_cmd_v2(Constants.GARMOUGAL_IP, Constants.GARMOUGAL_USERNAME, Constants.GARMOUGAL_PASSWORD, cmd)


def run_monitor_one_shot(ignore_patterns):
  global records
  global parse_start_time
  temp_dest="~/.gc_history"
  alert = False
  matched = None

  # Make user editable copy
  remote_cmd = f'cp {Constants.ORIGIN} {temp_dest} && chmod 777 {temp_dest} && stat -f "%Sm %N" {Constants.ORIGIN}'
  remote_su_cmd = f'sudo -- sh -c "{remote_cmd}"'
  msg = NetHelpers.ssh_cmd_v2(Constants.GARMOUGAL_IP, Constants.GARMOUGAL_USERNAME, Constants.GARMOUGAL_PASSWORD, remote_su_cmd)

  # Process and fetch minimal info
  remote_cmd=f"sqlite3 {temp_dest} \"SELECT last_visit_time, datetime(datetime(last_visit_time / 1000000 + (strftime('%s', '1601-01-01')), 'unixepoch'), 'localtime'), url FROM urls ORDER BY last_visit_time DESC LIMIT 15\" && rm {temp_dest}"
  msg2 = NetHelpers.ssh_cmd_v2(Constants.GARMOUGAL_IP, Constants.GARMOUGAL_USERNAME, Constants.GARMOUGAL_PASSWORD, remote_cmd)

  for record in reversed(msg2.split("\n")):
    data = record.split("|")
    if len(data) != 3:
      # Malformed. Ignore.
      continue

    data[0] = int(data[0])
    if data[0] <= parse_start_time:
      # We've already digested this record
      pass
    elif re.search(ignore_patterns, data[2]):
      msg += f"Ignoring: "
    elif any([re.search(pattern, data[2]) for pattern in Constants.BLACKLIST]):
      alert = True
      msg += f"ALERT!! "
      res = get_tld(data[2], as_object=True) #Get the root as an object
      matched = res.fld
    msg += f"[{data[1]}] {data[2]})\n"

    if data[0] > parse_start_time:
      parse_start_time = data[0]
      records[data[1]] = data[2]

  return(alert, msg, matched)


#### Main Routine ####
if __name__ == "__main__":
  parser = argparse.ArgumentParser(description = "Rian Browser Usage Alerting")
  parser.add_argument('--start_after_seconds',
                      help    = 'Seconds to sleep/not alert after starting',
                      type    = int,
                      default = 0)
  parser.add_argument('--ignore_patterns',
                      help    = 'Additional Regexes to ignore',
                      type    = str,
                      default = "LALA")
  parser.add_argument('--send_sms',
                      help    = 'Send SMS',
                      action  = 'store_true',
                      default = False)
  parser.add_argument('--always_email',
                      help    = 'Send email report',
                      action  = 'store_true',
                      default = False)
  args = parser.parse_args()

  logfile = '%s/%s.log' % (Constants.LOGGING_DIR, os.path.basename(__file__))
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  msg = refresh_dns_cache()
  print(f"Refreshed DNS at {msg}")
  print(f"Start monitoring after {args.start_after_seconds} seconds ...")
  time.sleep(args.start_after_seconds)

  count = 0
  while True:
    count += 1
    alert = False
    currtime = time.localtime()

    try:
      (alert, msg, matched) = run_monitor_one_shot(args.ignore_patterns)
    except Exception as e:
      msg = f'{e}'
      raise(e)

    logging.info(f'{count}: {msg}')
    if count < 2 and not args.always_email:
      # Bootstrap, don't run alerting
      print(f'{count}: {msg}')
    elif alert and (args.always_email or \
        (currtime.tm_hour >= Constants.HR_START_MONITORING and \
        currtime.tm_hour < Constants.HR_STOP_MONITORING) ):
      if args.send_sms:
        temp = msg.split('\n')[0]
        logging.info(f"Sending SMS: {temp}")
        MyTwilio.sendsms(f"Matched: {matched}")
      else:
        print(f'{count}: {msg}')
        for i in range(3):
          print("\a") # , end='') ## Doesn't work
          time.sleep(1)

    if len(records) > 0:
      if args.always_email or \
          (currtime.tm_hour == Constants.HR_EMAIL and currtime.tm_min == 0):
        msg = "\n".join([ f"[{k}]: {v}" for k,v in records.items()])
        records = {} # Email has gone out. Let's reset
        Mailer.sendmail(topic="[BrowsingMonitor]", alert=False, message=msg, always_email=args.always_email)
    time.sleep(Constants.REFRESH_DELAY)
