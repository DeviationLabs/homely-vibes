#!/usr/bin/env python3

import asyncio
from tesla_api import TeslaApiClient

from lib import Constants


async def save_token(token):
    open("token_file", "w").write(token)


async def main():
    async with TeslaApiClient(email, password, on_new_token=save_token) as client:
        await client.authenticate()


async def main_vehicle(email, password, token):
    async with TeslaApiClient(email, password, token, on_new_token=save_token) as client:
        vehicles = await client.list_vehicles()
        for v in vehicles:
            print(v.vin)
            await v.controls.flash_lights()


async def main_energy(email, password, token):
    client = TeslaApiClient(email, password, token, on_new_token=save_token)
    energy_sites = await client.list_energy_sites()
    print("Number of energy sites = %d" % (len(energy_sites)))
    assert len(energy_sites) == 1
    reserve = await energy_sites[0].get_backup_reserve_percent()
    print("Backup reserve percent = %d" % (reserve))
    print("Increment backup reserve percent")
    await energy_sites[0].set_backup_reserve_percent(reserve + 1)
    client.close()


def initialize():
    email = password = token = None
    try:
        token = open("token_file").read()
    except OSError:
        email = Constants.TESLA_EMAIL
        password = Constants.TESLA_PASSWORD
    return email, password, token


if __name__ == "__main__":
    email, password, token = initialize()
    asyncio.run(main_vehicle(email, password, token))
    email, password, token = initialize()
    asyncio.run(main_energy(email, password, token))

    # This is python3
#    loop = asyncio.get_event_loop()
#    loop.run_until_complete(main_vehicle())
#    loop.run_until_complete(main_energy(email, password, token))
