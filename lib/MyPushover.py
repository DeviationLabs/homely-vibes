#!/usr/bin/env python3
import http.client
import urllib
from lib import Constants
import logging


def send_pushover(rcpt, msg):
    conn = http.client.HTTPSConnection("api.pushover.net:443")
    try:
        conn.request(
            "POST",
            "/1/messages.json",
            urllib.parse.urlencode(
                {
                    "token": Constants.PUSHOVER_TOKEN,
                    "user": Constants.PUSHOVER_USER,
                    "message": msg,
                }
            ),
            {"Content-type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        logging.debug(f"Sent message to {rcpt} with resp: {resp}")
    except Exception as e:
        logging.warning(f"{e}")


if __name__ == "__main__":
    send_pushover(Constants.POWERWALL_PUSHOVER_RCPT, "test notification")
