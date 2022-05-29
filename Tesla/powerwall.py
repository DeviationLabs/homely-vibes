#!/usr/bin/env python3

# https://github.com/jrester/tesla_powerwall
from tesla_powerwall import Powerwall
#from tesla_powerwall import User
#from tesla_powerwall import API
#from tesla_powerwall.helpers import assert_attribute ## PW status
from tesla_powerwall.helpers import convert_to_kw

import Constants

# Create a simple powerwall object by providing the IP
powerwall = Powerwall(Constants.POWERWALL_IP)

# Create a powerwall object with more options
"""
powerwall = Powerwall(
    endpoint="<ip of your powerwall>",
    # Configure timeout; default is 10
    timeout=10,
    # Provide a requests.Session
    http_sesion=None,
    # Whether to verify the SSL certificate or not
    verify_ssl=False,
    disable_insecure_warning=True,
    # Set the API to expect a specific version of the powerwall software
    pin_version=None
)
"""

# Login as customer with email
powerwall.login(Constants.POWERWALL_PASSWORD, Constants.POWERWALL_EMAIL)
powerwall.detect_and_pin_version()

# Check if we are logged in
# This method only checks wether a cookie with a Bearer token exists
# It does not verify whether this token is valid
print (f"Checking auth status of PW: {powerwall.is_authenticated()}")

# Manually create API object
#api = API(f'https://{POWERWALL_IP}/')

# From existing powerwall
api = powerwall.get_api()

# Perform get on 'system_status/soe'
soe = api.get_system_status_soe()
#print(f"Got SOE:{soe}")

installer = api.get_installer()
#print(f"Got installer:{installer}")

charge = powerwall.get_charge()
print(f"Got Charge:{charge}")

status = powerwall.get_status()
#print(f"Got Status: {status}")

'''
status.version
#=> '1.49.0'
status.up_time_seconds
#=> datetime.timedelta(days=13, seconds=63287, microseconds=146455)
status.start_time
#=> datetime.datetime(2020, 9, 23, 23, 31, 16, tzinfo=datetime.timezone(datetime.timedelta(seconds=28800)))
status.device_type
'''

energy = powerwall.get_energy()
print(f"Got Energy: {energy}")
capacity = powerwall.get_capacity()
print(f"Got Capacity: {capacity}")

batteries = powerwall.get_batteries()
#print (f"Batteries: {batteries}")
'''
#=> [<Battery ...>, <Battery ...>]
batteries[0].part_number
#=> "XXX-G"
batteries[0].serial_number
#=> "TGXXX"
batteries[0].energy_remaining
#=> 7378 (W)
batteries[0].capacity
#=> 14031 (W)
batteries[0].energy_charged
#=> 5525740 (W)
batteries[0].energy_discharged
#=> 4659550 (W)
batteries[0].wobble_detected
'''

meters = powerwall.get_meters()
#print (f"Meters: {meters}")
'''
meters.solar.get_power()
#=> 0.4 (in kWh)
meters.solar.instant_power
#=> 409.941801071167 (in watts)
meters.solar.is_drawing_from()
#=> True
meters.load.is_sending_to()
#=> True
meters.battery.is_active()
#=> False
# Different precision settings might return different results
meters.battery.is_active(precision=5)
#=> True
'''

'''
(Pdb) powerwall.get_batteries()[0].energy_remaining
12878
(Pdb) powerwall.get_batteries()[0].capacity
13667
'''

import pdb; pdb.set_trace()
try:
    powerwall.logout()
except Exception as e:
    # we're trying to decode a None and throwing. Suppress?
    print(f"Got {e}")


