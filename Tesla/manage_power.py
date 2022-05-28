#!/usr/bin/env python3
# Uses TelsaPy written by Tim Dorssers
import argparse
import ast
from dataclasses import dataclass
from importlib import reload
import json
import logging
import os
import sys
import time
import Constants
import Mailer
import MyTwilio
from TeslaPy.teslapy import Tesla, Vehicle, Battery, SolarPanel


SMS_RCPT = '+14083757351' # Move to Constants.
POLL_TIME = 180 ## 300
DECISION_CONFIDENCE = 2

@dataclass
class OpModeConfig:
  time_start: int
  time_end: int
  pct_thresh_upper: int
  pct_thresh_lower: int
  pct_min: int
  op_mode: str
  reason: str

# How this works: Both ""customer_preferred_export_rule", "allow_charge_from_grid_with_solar_installed"
# are enforced to False for "self_consumption" mode, so we permanently set these to True in the tesla
# app, then simply have to toggle the self_consumption mode at the right time.
#
# -- Set the min battery threshold per your convenience. The last 5% cannot be extracted, so at 20%
# threshold, we have just about 2 hours of power reserves - Scary, so we will charge back up to 30%
# as soon as rates drop, then go back to self_consumption.
# -- For rainy days, we want to top just before we enter peak rates, but careful - it takes time to top off.
# hence multiple thresholds.
# -- We dump powerwall to grid twice. Once, opportunistically just before peak rate ends. And
# then everything left before end of shoulder.
# Recall = 1% is 0.135 kWh => base drain rate  or ~0.5kWh is 3.5%/hr
decision_points = [
  OpModeConfig(1900, 2100, 100, 70, 35, "autonomous", "Peak surplus #1. Dump.."),
  OpModeConfig(1930, 2300, 100, 53, 35, "autonomous", "Peak surplus #2. Dump.."),
  OpModeConfig(1945, 2300, 100, 42, 35, "autonomous", "Peak surplus #3. Dump.."),
  OpModeConfig(2000, 2300, 100, 35, 32, "autonomous", "Peak surplus #4. Dump.."),
  OpModeConfig(2040, 2100, 100, 32, 30, "autonomous", "Peak surplus #5. Dump.."),
  OpModeConfig(1900, 2300,  35,  0, 20, "self_consumption", "Reserve for shoulder. No dump"),
  OpModeConfig(2340, 2359, 100,  0, 20, "autonomous", "Prep for recharge from grid."),
  OpModeConfig( 000, 1500, 100, 30, 40, "self_consumption", "Reserves rebuilt. Hold"),
  OpModeConfig(1200, 1500,  60,  0, 20, "autonomous", "Prep for shoulder #1. Drawdown.."),
  OpModeConfig(1400, 1500,  90,  0, 20, "autonomous", "Prep for shoulder #2. Drawdown..2"),
  OpModeConfig(1600, 2000, 100,  0, 20, "self_consumption", "In Peak. Discharge"),
  OpModeConfig( 000, 2359, 100,  0, 20, None, "Do Nothing..."),
]


def main(args):
  try:
    with Tesla(args.email, verify=False, proxy=None, sso_base_url=None) as tesla:
      all_prod = tesla.vehicle_list() + tesla.battery_list() + tesla.solar_list()
      product = tesla.battery_list()[0]
      logging.info(f'{len(all_prod)} product(s), {product["site_name"]} selected:')
      loop_count = 0
      fail_count = 0
      decision = list()

      while True:
        loop_count += 1
        currtime = time.localtime()
        reload(Constants)
        logging.info(f'Count {loop_count}')

        try:
          product.get_battery_data()
          pct = product["energy_left"]/product["total_pack_energy"] * 100
          assert pct > 0, "Suprious 0 in battery read"

          op_mode = product["operation"]
          can_export = product["components"].get("customer_preferred_export_rule", "Not Found")
          can_grid_charge = not product["components"].get("disallow_charge_from_grid_with_solar_installed", False)
          assert (can_export == "battery_ok" and can_grid_charge), f"Error in config for export:{can_export} and grid_charge:{can_grid_charge}"

          fail_count = 0
        except Exception as e:
          logging.warn(f"Powerwall read failed with {e}")
          fail_count += 1
          if fail_count > 10:
            raise AssertionError(f"Continuously failing PW test. Error:{e}")
          time.sleep(POLL_TIME)
          continue
        logging.debug(json.dumps(product))
        logging.info(f"%:{pct:.2f}  Mode:{op_mode}  Export:{can_export}  Grid Charge:{can_grid_charge}")

        for point in decision_points:
          currtime_val = currtime.tm_hour * 100 + currtime.tm_min
          # Rules are in strict precedence. Find the first rule that applies.
          if currtime_val >= point.time_start and currtime_val <= point.time_end:
            if pct <= point.pct_thresh_upper and pct >= point.pct_thresh_lower:
              # Rule applies. Send command if needed, do not process further
              logging.info(f"Matched rule: {point}")
              decision.append(point.op_mode)
              if len(set(decision)) > 1:
                logging.warn(f"Oops. some spurious decision averted...{decision}")
                decision = [point.op_mode]
              if point.op_mode and op_mode != point.op_mode and len(decision) >= DECISION_CONFIDENCE:
                status = product.set_operation(point.op_mode)
                status2 = product.set_backup_reserve_percent(int(point.pct_min))
                msg = f"Updating to: {point.reason}, bkp = {point.pct_min}%% Status: {status} // status2"
                logging.warn(msg)
                if args.send_sms:
                  MyTwilio.sendsms(SMS_RCPT, msg)
              break  # out of for loop

        # Sleep, then while True loop...
        time.sleep(POLL_TIME)

  except EnvironmentError as e:
    logging.error(f"Oops. Telsa token expired? Run gui.py direclty from TeslaPy. Error: {e}")
    if args.send_sms:
      MyTwilio.sendsms(SMS_RCPT, "Oops. Telsa token expired? Run gui.py direclty from TeslaPy")
  except Exception as e:
    logging.error(e)
    if args.send_sms:
       MyTwilio.sendsms(SMS_RCPT, e.__repr__())
  return


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Tesla Owner API CLI')
  parser.add_argument('-d', '--debug', action='store_true',
                       help='set logging level to debug')
  parser.add_argument('-e', dest='email', help='login email', default='abutala@gmail.com')
  parser.add_argument('-k', dest='keyvalue', help='API parameter (key=value)',
            action='append', type=lambda kv: kv.split('=', 1))
  parser.add_argument('-q','--quiet', action='store_true', help="Don't print to stdout")
  parser.add_argument('--send_sms',
                      help  = 'Send SMS using Twilio',
                      action  = 'store_true')

  args = parser.parse_args()

  logfile = '%s/%s.log' % (Constants.LOGGING_DIR, os.path.basename(__file__))
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.INFO)
  if args.debug:
      logging.getLogger().setLevel(logging.DEBUG)
  if not args.quiet:
      logging.getLogger().addHandler(logging.StreamHandler())
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  main(args)
