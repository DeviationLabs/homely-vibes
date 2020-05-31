#!/usr/bin/env python3.6
import argparse
from importlib import reload
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


def refresh_dns_cache(client):
  # Purge DNS cache before start of tailer...
  cmd = "sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder && date"
  return NetHelpers.ssh_cmd_v2(client, cmd)


def run_monitor_one_shot(client, origin_file, ignore_patterns):
  global records
  global parse_start_time
  temp_dest="~/.gc_history"
  alert = False
  matched = None

  # Make User History and fetch minimal info
  remote_cmd  = f'sudo cp -p {origin_file} {temp_dest}'
  remote_cmd += f' && sudo chmod 777 {temp_dest}'
  remote_cmd += f' && sudo stat -f "%Sm %N" {temp_dest}'
  remote_cmd += f" && sqlite3 {temp_dest} \"SELECT last_visit_time, datetime(datetime(last_visit_time / 1000000 + (strftime('%s', '1601-01-01')), 'unixepoch'), 'localtime'), url FROM urls ORDER BY last_visit_time DESC LIMIT 15\""
  remote_cmd += f' && rm {temp_dest}'
  msg = NetHelpers.ssh_cmd_v2(client, remote_cmd)

  response = msg.split("\n");
  msg = f"{response[0]}\n"
  for record in reversed(response[1:]):
    data = record.split("|")
    if len(data) != 3:
      # Malformed. Ignore.
      continue

    data[0] = int(data[0])
    if data[0] <= parse_start_time:
      # We've already digested this record
      continue
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
  parser.add_argument('--machine',
                      help    = 'short name of machine to monitor',
                      type    = str,
                      default = "garmougal")
  parser.add_argument('--send_sms',
                      help    = 'Send SMS',
                      action  = 'store_true',
                      default = False)
  parser.add_argument('--always_email',
                      help    = 'Send email report',
                      action  = 'store_true',
                      default = False)
  args = parser.parse_args()

  logfile = '%s/%s.%s.log' % (Constants.LOGGING_DIR, os.path.basename(__file__), args.machine)
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  time.sleep(args.start_after_seconds)

  host = Constants.NODES[args.machine]
  try:
    client = NetHelpers.ssh_connect(host["ip"], host["username"], host["password"])
    msg = refresh_dns_cache(client)
    print(f"Refreshed DNS at {msg}")
    print(f"Start monitoring after {args.start_after_seconds} seconds ...")
  except Exception as e:
    client = None
    print(f"Machine offline, but still continuing...")
    logging.info(f"Machine offline, but still continuing...")

  count = 0
  last_checked_hr = -1
  while True:
    count += 1
    alert = False
    currtime = time.localtime()
    sleep_time = Constants.REFRESH_DELAY

    try:
      Constants = reload(Constants)
      host = Constants.NODES[args.machine]
      (alert, msg, matched) = run_monitor_one_shot(client, host["histfile"], args.ignore_patterns)
    except Exception as e:
      msg = f'{e}'
      try:
        # Most probable explanation is ssh has failed, so reconnect
        # TODO: Do only on the right exception messages
        client = NetHelpers.ssh_connect(host["ip"], host["username"], host["password"])
      except Exception as e:
        # Take a cooling off period.
        client = None
        msg += f'{e}'
        sleep_time = 300
        msg += f'\nSSH reconnect failed. Take a {sleep_time}s cooloff period...\n'

    print(f'{count}: {msg}')
    logging.info(f'{count}: {msg}')
    if alert:
      temp = msg.split('\n')[0]
      if (args.send_sms and (args.always_email or
        (count > 1 and currtime.tm_hour >= Constants.HR_START_MONITORING and \
         currtime.tm_hour < Constants.HR_STOP_MONITORING) ) ):
        logging.info(f"Badness Sending SMS: {temp}")
        for rcpt in host["sms_inform"]:
          MyTwilio.sendsms(rcpt, f"[BLACKLIST] Host: {args.machine}, Site: {matched}")
      else:
        logging.info(f"Badness No SMS: {temp}")
        for i in range(3):
          print("\a") # , end='') ## Doesn't work
          time.sleep(1)

    if (args.always_email or currtime.tm_hour == Constants.HR_EMAIL) and last_checked_hr != currtime.tm_hour:
      # Email on the correct hour
      msg = "Found records:\n" + "\n".join([ f"[{k}]: {v}" for k,v in records.items()])
      Mailer.sendmail(topic="[BrowsingMonitor]", alert=False, message=msg, always_email=True)
      records = {} # Email has gone out. Let's reset
    last_checked_hr = currtime.tm_hour

    time.sleep(sleep_time)
