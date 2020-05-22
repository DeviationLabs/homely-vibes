#!/usr/bin/env python3.6
from twilio.rest import Client
import Constants

def sendsms(msg):
  client = Client(Constants.TWILIO_SID, Constants.AUTH_TOKEN)
  for rcpt in Constants.SMS_TO:
    try:
      message = client.messages.create(
        body=msg,
        to=rcpt,
        from_=Constants.SMS_FROM
      )

      print(f'Sent message with id: {message.sid}')
    except Exception as e:
      print(f'{e}')

if __name__ == "__main__":
  sendsms("Test message from Amit")
