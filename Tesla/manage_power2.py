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
POLL_TIME = 10 # 80 ## 300
DECISION_CONFIDENCE = 2

@dataclass
class OpModeConfig:
  time_start: int
  time_end: int
  pct_gradient_per_hr: int
  pct_thresh: int
  iff_higher: bool
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
# Recall: 1% is 0.135kWh ==> base drain rate of 0.5kWh is 3.5%/hr
decision_points = [
  OpModeConfig( 000, 1500,  0,  30,  True, 35, "self_consumption", "Nightly reserves rebuilt. Hold"),
  OpModeConfig(1200, 1500, 35, 100,  True, 20, "autonomous", "Prep for shoulder. Drawdown.."),
  OpModeConfig(1500, 1900,  0,   0,  True, 20, "self_consumption", "In Peak. Discharge"),
  OpModeConfig(1900, 2100, -5,  35,  True, 35, "autonomous", "End of peak surplus. Dump.."),
  OpModeConfig(1900, 2359, -4,  20, False, 20, "self_consumption", "Reserve for rest of day. No dump"),
  OpModeConfig(2340, 9900,  0,   0,  True, 20, "autonomous", "Prep for recharge. Dump residuals "),
]


def condition_matches(lhs, rhs, direction_up):
  if lhs > rhs and direction_up == True:
    # Gradient set for drain and okay to drain
    return True
  elif lhs < rhs and direction_up == False:
    # Grid charging needed
    return True
  return False


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
          assert pct > 0, "Spurious 0 in battery read"

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

#        pct = 34 # for debug - then delete
        for point in decision_points:
          currtime_val = currtime.tm_hour * 100 + currtime.tm_min
          # Rules are in strict precedence. Find the first rule that applies.
          if currtime_val >= point.time_start and currtime_val <= point.time_end:
            hrs_to_end = (int(point.time_end/100) - currtime.tm_hour) + \
                    (point.time_end%100 - currtime.tm_min) / 60
            trigger_pct = point.pct_thresh - (point.pct_gradient_per_hr * hrs_to_end)

            if condition_matches(pct, trigger_pct, point.iff_higher):
              # Rule applies. Send command if needed, do not process further
              logging.info(f"Matched rule at {trigger_pct}%: {point}")
              decision.append(point.op_mode)
              if len(set(decision)) > 1:
                logging.warn(f"Oops. some spurious decision averted...{decision}")
                decision = [point.op_mode]
              if op_mode != point.op_mode and len(decision) >= DECISION_CONFIDENCE:
                status = product.set_operation(point.op_mode)
                status2 = product.set_backup_reserve_percent(int(point.pct_min))
                msg = f"At: {pct}% Set rule: {point.reason}, Status: {status} // {status2}"
                logging.warn(msg)
                if args.send_sms:
                  MyTwilio.sendsms(SMS_RCPT, msg)
              break  # out of for loop
            else:
              logging.info(f"Skip: Trig:{trigger_pct}% {point}")
        else:
          logging.info(f"Matched no rule. Is that okay?")

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
