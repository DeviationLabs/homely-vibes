#!/usr/bin/env python3
from typing import Any, Tuple, Optional
import argparse
from importlib import reload
import os
import re
import sys
import time
from tld import get_tld
from lib import Constants
from lib import Mailer
from lib import MyTwilio
from lib import NetHelpers
from lib.logger import SystemLogger

logger = SystemLogger.get_logger(__name__)


records = {}
parse_start_time = 0


def refresh_dns_cache(client: Any) -> str:
    # Purge DNS cache before start of tailer...
    cmd = "sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder && date"
    return str(NetHelpers.ssh_cmd_v2(client, cmd))


def run_monitor_one_shot(
    client: Any, origin_file: str, ignore_patterns: str
) -> Tuple[bool, str, Optional[str]]:
    global records
    global parse_start_time
    temp_dest = "~/.gc_history"
    alert = False
    matched = None

    # Make User History and fetch minimal info
    remote_cmd = f"sudo cp -p {origin_file} {temp_dest}"
    remote_cmd += f" && sudo chmod 777 {temp_dest}"
    remote_cmd += f' && sudo stat -f "%Sm %N" {temp_dest}'
    remote_cmd += f" && sqlite3 {temp_dest} \"SELECT last_visit_time, datetime(datetime(last_visit_time / 1000000 + (strftime('%s', '1601-01-01')), 'unixepoch'), 'localtime'), url FROM urls ORDER BY last_visit_time DESC LIMIT 15\""
    remote_cmd += f" && rm {temp_dest}"
    msg = NetHelpers.ssh_cmd_v2(client, remote_cmd)

    response = msg.split("\n")
    msg = f"{response[0]}\n"
    for record in reversed(response[1:]):
        data = record.split("|")
        if len(data) != 3:
            # Malformed. Ignore.
            continue

        data[0] = int(data[0])
        if data[0] <= parse_start_time:
            # We've already digested this record
            continue
        elif re.search(ignore_patterns, data[2]):
            msg += "Ignoring: "
        elif any([re.search(pattern, data[2]) for pattern in Constants.BLACKLIST]):
            alert = True
            msg += "ALERT!! "
            res = get_tld(data[2], as_object=True)  # Get the root as an object
            matched = res.fld if hasattr(res, "fld") else None
        msg += f"[{data[1]}] {data[2]})\n"

        if data[0] > parse_start_time:
            parse_start_time = data[0]
            records[data[1]] = data[2]

    return (alert, msg, matched)


#### Main Routine ####
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rian Browser Usage Alerting")
    parser.add_argument(
        "--start_after_seconds",
        help="Seconds to sleep/not alert after starting",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--machine",
        help="short name of machine to monitor",
        type=str,
        default="garmougal",
    )
    parser.add_argument(
        "--send_sms",
        help="Send email report",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--always_email",
        help="Send email report",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    SEND_SMS_FLAG = f"/tmp/sms_enabled.{args.machine}"
    if args.send_sms:
        with open(SEND_SMS_FLAG, "w") as fp:
            pass
        logger.info("Enabling SMS")
    else:
        try:
            os.remove(SEND_SMS_FLAG)
        except OSError:
            pass
        logger.info("Disabling SMS")

    time.sleep(args.start_after_seconds)

    host = Constants.NODES[args.machine]
    try:
        client = NetHelpers.ssh_connect(host["ip"], host["username"], host["password"])
        msg = refresh_dns_cache(client)
        print(f"Refreshed DNS at {msg}")
        print(f"Start monitoring after {args.start_after_seconds} seconds ...")
    except Exception:
        client = None
        print("Machine offline, but still continuing...")
        logger.info("Machine offline, but still continuing...")

    cool_down_attempts = Constants.MIN_REPORTING_GAP

    last_checked_hr = -1
    only_ssh_fails_count = 0
    SSH_ALERT_DELAY_COUNT = 20
    while True:
        cool_down_attempts -= 1
        alert = False
        currtime = time.localtime()
        sleep_time = Constants.REFRESH_DELAY

        try:
            Constants = reload(Constants)
            host = Constants.NODES[args.machine]
            (alert, msg, matched) = run_monitor_one_shot(
                client, host["histfile"], host.get("whitelist", "")
            )
            if only_ssh_fails_count > SSH_ALERT_DELAY_COUNT:
                sms_inform = host.get("sms_inform", [])
                if isinstance(sms_inform, list):
                    for rcpt in sms_inform:
                        pass  # Will be handled below
                elif isinstance(sms_inform, str):
                    sms_inform = [sms_inform]
                for rcpt in sms_inform or []:
                    MyTwilio.sendsms(
                        rcpt,
                        f"[Success][{args.machine}] Ssh failure has self healed",
                    )
            only_ssh_fails_count = 0
        except Exception as e:
            msg = f"{e}"
            try:
                # Most probable explanation is ssh has failed, so reconnect and retry
                client = NetHelpers.ssh_connect(host["ip"], host["username"], host["password"])
                (alert, msg, matched) = run_monitor_one_shot(
                    client, host["histfile"], host.get("whitelist", "")
                )
            except Exception as e:
                # Take a cooling off period.
                client = None
                msg += f"{e}"
                sleep_time = Constants.REFRESH_DELAY * 10
                msg += f"\nSSH reconnect failed. Take a {sleep_time}s cooloff period...\n"
                if NetHelpers.ping_output(node=host["ip"]):
                    only_ssh_fails_count += 1
                    if only_ssh_fails_count == SSH_ALERT_DELAY_COUNT:
                        # ping succeeds but ssh failing for a while
                        sms_inform = host.get("sms_inform", [])
                        if isinstance(sms_inform, list):
                            for rcpt in sms_inform:
                                pass  # Will be handled below
                        elif isinstance(sms_inform, str):
                            sms_inform = [sms_inform]
                        for rcpt in sms_inform or []:
                            MyTwilio.sendsms(
                                rcpt,
                                f"[Error][{args.machine}] Ping up but ssh failing. Needs manual debug",
                            )

        print(msg)
        logger.info(msg)
        if alert:
            temp = msg.split("\n")[0]
            if os.path.exists(SEND_SMS_FLAG) and (
                args.always_email
                or (
                    cool_down_attempts <= 0
                    and currtime.tm_hour >= Constants.HR_START_MONITORING
                    and currtime.tm_hour < Constants.HR_STOP_MONITORING
                )
            ):
                logger.info(f"Badness Sending SMS: {temp}")
                cool_down_attempts = Constants.MIN_REPORTING_GAP
                sms_inform = host.get("sms_inform", [])
                if isinstance(sms_inform, list):
                    for rcpt in sms_inform:
                        pass  # Will be handled below
                elif isinstance(sms_inform, str):
                    sms_inform = [sms_inform]
                for rcpt in sms_inform or []:
                    MyTwilio.sendsms(rcpt, f"[BLACKLIST][{args.machine}] : {matched}")
            else:
                logger.info(f"Badness No SMS: {temp}")
                for i in range(3):
                    print("\a")  # , end='') ## Doesn't work
                    time.sleep(1)

        if (
            args.always_email or currtime.tm_hour == Constants.HR_EMAIL
        ) and last_checked_hr != currtime.tm_hour:
            # Email on the correct hour
            msg = "Found records:\n" + "\n".join([f"[{k}]: {v}" for k, v in records.items()])
            Mailer.sendmail(
                topic=f"[BrowserAlert][{args.machine}]",
                alert=False,
                message=msg,
                always_email=True,
            )
            records = {}  # Email has gone out. Let's reset
        last_checked_hr = currtime.tm_hour

        time.sleep(sleep_time)
