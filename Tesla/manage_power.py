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
DECISION_CONFIDENCE = 3

@dataclass
class OpModeConfig:
  time_start: int
  time_end: int
  pct_thresh_upper: int
  pct_thresh_lower: int
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
decision_points = [
  OpModeConfig(2000, 2100, 100, 38, "autonomous", "Peak hour and surplus. Discharge.."),
  OpModeConfig(2000, 2300,  35,  0, "self_consumption", "Keep some for shoulder"),
  OpModeConfig(2340, 9900, 100,  0, "autonomous", "Get ready to recharge from grid. Discharge everything."),
  OpModeConfig( 000, 1500, 100, 30, "self_consumption", "Reserves rebuilt. Hold at threshold"),
  OpModeConfig(1200, 1500,  60,  0, "autonomous", "Prepare for shoulder. Thresh1"),
  OpModeConfig(1400, 1500,  90,  0, "autonomous", "Prepare for shoulder. Thresh2"),
  OpModeConfig(1600, 2000, 100,  0, "self_consumption", "In Peak. Start discharging"),
  OpModeConfig( 000, 2359, 100,  0, None, "Do Nothing..."),
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
          fail_count = 0
          pct = product["energy_left"]/product["total_pack_energy"] * 100
          assert pct > 0
        except Exception as e:
          logging.warn(f"Powerwall read failed with {e}")
          fail_count += 1
          if fail_count > 10:
            if args.send_sms:
              MyTwilio.sendsms(SMS_RCPT, f"Continuously failing to read powerwall. Aborting... ")
            raise AssertionError("Unrecoverable, dying...")
          time.sleep(POLL_TIME)
          continue
        logging.debug(json.dumps(product))

        op_mode = product["operation"]
        can_export = product["components"].get("customer_preferred_export_rule", "Not Found")
        can_grid_charge = not product["components"].get("disallow_charge_from_grid_with_solar_installed", False)
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
                logging.warn(f"Updating to: {point.reason} Status: {status}")
                if args.send_sms:
                  MyTwilio.sendsms(SMS_RCPT, f"Updating to: {point.reason} Status: {status}")
              break  # out of for loop

        ''' Old way
        # If battery is not already charged by noon, then panic and send all solar to battery
        # This then continues through peak hour.
        # Else early morning, we want to be nice and self power.
        if currtime.tm_hour >= 12:
          if op_mode != "autonomous":
            status = product.api('OPERATION_MODE',default_real_mode="autonomous")
            if args.send_sms:
              MyTwilio.sendsms(SMS_RCPT, f"Switching to autonomous {status}")
        else:
          if op_mode != "self_consumption":
            status = product.set_operation("self_consumption")
            if args.send_sms:
              MyTwilio.sendsms(SMS_RCPT, f"Switching to self_consumption {status}")

        # If we are in off peak, and battery is depleted, give it some juice from grid
        if currtime.tm_hour < 10 and pct < 50 and not can_grid_charge:
          logging.info("Add logic for grid charging")
#          status = product.api('OPERATION_MODE',default_real_mode="autonomous")
        elif pct > 50 and can_grid_charge:
          logging.info("Let's disable grid charging")
#          status = product.api('OPERATION_MODE',default_real_mode="autonomous")

        # If it's getting late in the evening, and battery has juice, send surplus to grid.
        if currtime.tm_hour > 20  and pct > 35 and can_export == 'pv_only':
          logging.info("Add logic for export")
        elif pct < 35 and can_export == 'battery_ok':
          logging.info("Stop exporting -- We need for ourselves")
        '''

        # Check once a minute (Maybe 5 mins would be fine too?)
        time.sleep(POLL_TIME)

  except EnvironmentError as e:
    logging.error(f"Oops. Telsa token expired? Run gui.py direclty from TeslaPy. Error: {e}")
    if args.send_sms:
      MyTwilio.sendsms(SMS_RCPT, "Oops. Telsa token expired? Run gui.py direclty from TeslaPy")


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


