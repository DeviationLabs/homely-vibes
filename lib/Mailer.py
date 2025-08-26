#!/usr/bin/env python3
import calendar
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from lib import Constants


def sendmail(topic, alert, message, always_email=Constants.ALWAYS_EMAIL):
    today = datetime.datetime.today()
    day_today = calendar.day_name[today.weekday()]
    hour_today = today.hour
    minute_today = today.minute
    ts = "%s %02d:%02d " % (day_today, hour_today, minute_today)

    if always_email or alert:
        try:
            msg = MIMEMultipart()
            msg["From"] = Constants.EMAIL_FROM
            msg["To"] = Constants.EMAIL_TO
            flag = "[ALERT]" if alert else ""
            msg["Subject"] = "%s%s %s %02d:%02d" % (
                topic,
                flag,
                day_today,
                hour_today,
                minute_today,
            )
            if "<html>" in message:
                msg.attach(MIMEText(message, "html"))
            else:
                msg.attach(MIMEText(message, "plain"))

            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.ehlo()
            server.login(Constants.GMAIL_USERNAME, Constants.GMAIL_PASSWORD)
            server.sendmail(Constants.EMAIL_FROM, Constants.EMAIL_TO, msg.as_string())
            server.close()
            logging.info("%s Email sent!" % ts)
        except smtplib.SMTPDataError as e:
            logging.error("%s Something went wrong..." % ts)
            logging.error(e)
            print(e)
    else:
        logging.info("%s No email" % ts)
