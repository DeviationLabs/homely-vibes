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

rcpt = '+14083757351' # Move to Constants.

def main(args):
    try:
        with Tesla(args.email, verify=False, proxy=None, sso_base_url=None) as tesla:
            all_prod = tesla.vehicle_list() + tesla.battery_list() + tesla.solar_list()
            product = tesla.battery_list()[0]
            logging.info(f'{len(all_prod)} product(s), {product["site_name"]} selected:')
            loop_count = 0

            while True:
                loop_count += 1
                currtime = time.localtime()
                reload(Constants)
                logging.info(f'Count {loop_count}')

                product.get_battery_data()
                logging.debug(json.dumps(product))

                pct = product["energy_left"]/product["total_pack_energy"] * 100
                op_mode = product["operation"]
                can_export = product["components"].get("customer_preferred_export_rule", "Not Found")
                can_grid_charge = not product["components"].get("disallow_charge_from_grid_with_solar_installed", False)
                logging.info(f"%:{pct:.2f}  Mode:{op_mode}  Export:{can_export}  Grid Charge:{can_grid_charge}")

                # If battery is not already charged by noon, then panic and send all solar to battery
                # This then continues through peak hour.
                # Else early morning, we want to be nice and self power.
                if currtime.tm_hour >= 12:
                    if op_mode != "autonomous":
                        status = product.api('OPERATION_MODE',default_real_mode="autonomous")
                        if args.send_sms:
                            MyTwilio.sendsms(rcpt, f"Switching to autonomous {status}")
                else:
                    if op_mode != "self_consumption":
                        status = product.set_operation("self_consumption")
                        if args.send_sms:
                            MyTwilio.sendsms(rcpt, f"Switching to self_consumption {status}")

                # If we are in off peak, and battery is depleted, give it some juice from grid
                if currtime.tm_hour < 10 and pct < 50 and not can_grid_charge:
                    logging.info("Add logic for grid charging")
#                    status = product.api('OPERATION_MODE',default_real_mode="autonomous")
                elif pct > 50 and can_grid_charge:
                    logging.info("Let's disable grid charging")
#                    status = product.api('OPERATION_MODE',default_real_mode="autonomous")

                # If it's getting late in the evening, and battery has juice, send surplus to grid.
                if currtime.tm_hour > 20  and pct > 35 and can_export == 'pv_only':
                    logging.info("Add logic for export")
                elif pct < 35 and can_export == 'battery_ok':
                    logging.info("Stop exporting -- We need for ourselves")

                # Check once a minute (Maybe 5 mins would be fine too?)
                time.sleep(60)

    except EnvironmentError as e:
        logging.error("Oops. Telsa token expired? Run gui.py direclty from TeslaPy")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tesla Owner API CLI')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='set logging level to debug')
    parser.add_argument('-e', dest='email', help='login email', default='abutala@gmail.com')
    parser.add_argument('-k', dest='keyvalue', help='API parameter (key=value)',
                        action='append', type=lambda kv: kv.split('=', 1))
    parser.add_argument('--send_sms',
                      help    = 'Send SMS using Twilio',
                      action  = 'store_true',
                      default = False)

    args = parser.parse_args()

    logfile = '%s/%s.log' % (Constants.LOGGING_DIR, os.path.basename(__file__))
    log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
    logging.basicConfig(filename=logfile, format=log_format, level=logging.DEBUG if args.debug else logging.INFO)
    logging.info('============')
    logging.info('Invoked command: %s' % ' '.join(sys.argv))

    main(args)


