#!/usr/bin/env python3
import calendar
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from lib.config import get_config


def sendmail(topic, alert, message, always_email=False):
    today = datetime.datetime.today()
    day_today = calendar.day_name[today.weekday()]
    hour_today = today.hour
    minute_today = today.minute
    ts = "%s %02d:%02d " % (day_today, hour_today, minute_today)

    if always_email or alert:
        try:
            cfg = get_config()
            msg = MIMEMultipart()
            msg["From"] = cfg.email.from_addr
            msg["To"] = cfg.email.to_addr
            flag = "[ALERT]" if alert else ""
            msg["Subject"] = "%s%s %s %02d:%02d" % (
                topic,
                flag,
                day_today,
                hour_today,
                minute_today,
            )
            if "<html>" in message:
                msg.attach(MIMEText(message, "html", "utf-8"))
            else:
                # Use plain text with UTF-8 encoding to preserve formatting
                msg.attach(MIMEText(message, "plain", "utf-8"))

            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.ehlo()
            server.login(cfg.email.gmail_username, cfg.email.gmail_password)
            server.sendmail(cfg.email.from_addr, cfg.email.to_addr, msg.as_string())
            server.close()
            logging.info("%s Email sent!" % ts)
        except smtplib.SMTPDataError as e:
            logging.error("%s Something went wrong..." % ts)
            logging.error(e)
            print(e)  # This gets trapped by cron
    else:
        logging.info("%s No email" % ts)
