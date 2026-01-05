#!/usr/bin/env python3
from twilio.rest import Client
from lib.config import get_config
import logging


def sendsms(rcpt, msg):
    cfg = get_config()
    client = Client(cfg.twilio.sid, cfg.twilio.auth_token)
    try:
        message = client.messages.create(body=msg, to=rcpt, from_=cfg.twilio.sms_from)

        logging.debug(f"Sent message to {rcpt} with id: {message.sid}")
    except Exception as e:
        logging.warning(f"{e}")


if __name__ == "__main__":
    cfg = get_config()
    sendsms(cfg.tesla.powerwall_sms_rcpt, "test notification")
