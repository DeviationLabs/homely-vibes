#!/usr/bin/env python3
# Uses TelsaPy written by Tim Dorssers
import argparse
import ast
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
      product = tesla.battery_list()[0]
      logging.info(f'{product["site_name"]} discovered')
      loop_count = 0
      fail_count = 0
      decision = list()
      pct = old_pct = 00

      while True:
        loop_count += 1
        if fail_count > 10:
          raise AssertionError(f"Continuously failing PW test. Exiting..")

        currtime = time.localtime()
        reload(Constants)
        SMS_RCPT = Constants.POWERWALL_SMS_RCPT
        POLL_TIME = Constants.POWERWALL_POLL_TIME
        DECISION_CONFIDENCE = Constants.POWERWALL_DECISION_CONFIDENCE
        DECISION_POINTS = Constants.POWERWALL_DECISION_POINTS
        logging.info(f'Count {loop_count}')

        try:
          product.get_battery_data()
          op_mode = product["operation"]
          backup_pct = product["backup"]["backup_reserve_percent"]
          can_export = product["components"].get("customer_preferred_export_rule", "Not Found")
          can_grid_charge = not product["components"].get("disallow_charge_from_grid_with_solar_installed", False)
          assert (can_export == "battery_ok" and can_grid_charge), f"Error in PW config. Got export: {can_export}, grid_charge: {can_grid_charge}"

          new_pct = round(product["energy_left"]/product["total_pack_energy"] * 100, 2)
          if new_pct <= 0:
            new_pct = pct + ((pct - old_pct) * (old_pct > 0)) # extrapolate only if old_pct is valid
            logging.warning(f"Got bad battery % data. Patch as {new_pct}% and continue..")
            fail_count += 1
          else:
            fail_count = 0
          old_pct = pct
          pct = new_pct
        except Exception as e:
          logging.warning(f"Powerwall read failed with {e}. Discarding...")
          logging.debug(f"Got:{product}")
          fail_count += 1
          time.sleep(POLL_TIME)
          continue
        logging.debug(json.dumps(product))
        logging.info(f"Read %:{pct:.2f}  Mode:{op_mode}  Export:{can_export}  Grid Charge:{can_grid_charge}")

        for point in DECISION_POINTS:
          currtime_val = currtime.tm_hour * 100 + currtime.tm_min
          # Rules are in strict precedence. Find the first rule that applies.
          if currtime_val >= point.time_start and currtime_val < point.time_end:
            hrs_to_end = (int(point.time_end/100) - currtime.tm_hour) + \
                    (point.time_end%100 - currtime.tm_min + (POLL_TIME/60/2)) / 60
            trigger_pct = round(point.pct_thresh - (point.pct_gradient_per_hr * hrs_to_end), 2)

            if condition_matches(pct, trigger_pct, point.iff_higher):
              # Rule applies. Send command if needed, do not process further
              logging.info(f"Matched rule at {trigger_pct}%: {point}")
              decision.append(point.op_mode)
              if len(set(decision)) > 1:
                logging.warning(f"New decision {point.op_mode} indicated. Waiting for count: {DECISION_CONFIDENCE}")
                decision = [point.op_mode]
              status = status2 = None
              if op_mode != point.op_mode and len(decision) >= DECISION_CONFIDENCE:
                status = f"{point.op_mode} "
                status += product.set_operation(point.op_mode)
              if backup_pct !=  point.pct_min:
                status2 = f"{point.pct_min} "
                status2 += product.set_backup_reserve_percent(int(point.pct_min))

              if status or status2:
                msg = f"At:{pct}% Rule: {point.reason}" + \
                      f"  Mode:{status or 'No change'}  Reserve %:{status2 or 'No change'}"
                logging.warning(msg)
                if args.send_sms:
                  MyTwilio.sendsms(SMS_RCPT, msg)
              break  # out of for loop
            else:
              logging.info(f"In time window, but skip: Trig:{trigger_pct}% {point}")
        else:
          logging.warning(f"Matched no rule. Is that okay?")

        # Sleep, then while True loop...
        time.sleep(POLL_TIME)

  except EnvironmentError as e:
    logging.error(f"Oops. Telsa token expired? Run gui.py direclty from TeslaPy. Error: {e}")
    MyTwilio.sendsms(SMS_RCPT, "Oops. Telsa token expired? Run gui.py direclty from TeslaPy")
  except Exception as e:
    logging.error(e)
    if args.send_sms:
       MyTwilio.sendsms(SMS_RCPT, e.__repr__())
  logging.error(f"Will hard exit after delay of 3600 seconds to prevent respawn churn...\n\n\n\n\n")
  time.sleep(3600) # Don't quit early, as we'll just keep respawning
  return


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Tesla Owner API CLI')
  parser.add_argument('-d', '--debug', action='store_true',
                       help='set logging level to debug')
  parser.add_argument('-e', dest='email', help='login email', default=Constants.POWERWALL_EMAIL)
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

  logging.warn(f"Exiting..\n\n")
