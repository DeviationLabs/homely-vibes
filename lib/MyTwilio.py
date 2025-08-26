#!/usr/bin/env python3
from twilio.rest import Client
from lib import Constants
import logging


def sendsms(rcpt, msg):
    client = Client(Constants.TWILIO_SID, Constants.AUTH_TOKEN)
    try:
        message = client.messages.create(body=msg, to=rcpt, from_=Constants.SMS_FROM)

        logging.debug(f"Sent message to {rcpt} with id: {message.sid}")
    except Exception as e:
        logging.warning(f"{e}")


if __name__ == "__main__":
    sendsms(Constants.POWERWALL_SMS_RCPT, "test notification")
