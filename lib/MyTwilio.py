#!/usr/bin/env python3.6
from twilio.rest import Client
import Constants
import logging

def sendsms(rcpt, msg):
  client = Client(Constants.TWILIO_SID, Constants.AUTH_TOKEN)
  try:
    message = client.messages.create(
      body=msg,
      to=rcpt,
      from_=Constants.SMS_FROM
    )

    logging.debug(f'Sent message to {rcpt} with id: {message.sid}')
  except Exception as e:
    logging.warn(f'{e}')
