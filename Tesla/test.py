import asyncio
from tesla_api import TeslaApiClient

import Constants

async def save_token(token):
    open("token_file", "w").write(token)

async def main():
    async with TeslaApiClient(email, password, on_new_token=save_token) as client:
        await client.authenticate()
