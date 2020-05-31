#!/usr/bin/env python3.6
from twilio.rest import Client
import Constants

def sendsms(rcpt, msg):
  client = Client(Constants.TWILIO_SID, Constants.AUTH_TOKEN)
  try:
    message = client.messages.create(
      body=msg,
      to=rcpt,
      from_=Constants.SMS_FROM
    )

    print(f'Sent message to {rcpt} with id: {message.sid}')
  except Exception as e:
    print(f'{e}')
