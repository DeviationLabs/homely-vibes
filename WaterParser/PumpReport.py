#!/usr/bin/env python3
import collections
import logging
import os
import time
from lib.config import get_config
import Mailer
from TuyaLogParser import readSummaryFile

THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
cfg = get_config()


def custom_sort(record):
    zoneName = record[1]["zoneName"].split()
    if len(zoneName) < 3:
        # Not a real zone, just return first char in name
        return ord(zoneName[0][0])
    else:
        zoneType = zoneName[1][1]
        number = zoneName[0][1:]
        offsets = {"D": 400, "B": 200, "S": 100}  # Drip/Bubblers/Sprinkers
        sortOrder = offsets.get(zoneType, 0) + int(number)
        return sortOrder


# Flag all zone where latest rate is greater than average of the last N days.
def genSendMessage(always_email):
    cfg = get_config()
    aggregated = collections.defaultdict(lambda: {"pumpTime": 0, "toggles": 0, "runTime": 0})
    latest = collections.defaultdict(
        lambda: {
            "pumpTime": 0,
            "pumpRate": 0,
            "runTime": 0,
            "zoneName": None,
            "startEpoch": 0,
        }
    )
    aggregatedPumpTime = 0
    aggregatedToggles = 0
    summary = readSummaryFile(cfg.paths.json_summary_patch_file)
    sorted_summary_items = sorted(list(summary.items()))
    lastEndTime = None

    # Find the average, until we cover 10x the min time requirement for reporting. This is the average burn rate
    # We dont want to include the last 14 days, since this is the window we want to validate
    for ts, record in sorted_summary_items[
        -14 : -(cfg.water_monitor.days_lookback * cfg.water_monitor.logrotate_per_day) : -1
    ]:
        zonesStats = record["zonesStats"]
        for zoneNumStr, zoneStats in zonesStats.items():
            if aggregated[zoneNumStr]["toggles"] < cfg.water_monitor.pump_toggles_count:
                aggregated[zoneNumStr]["toggles"] += zoneStats.get("toggles", 0)
                aggregated[zoneNumStr]["pumpTime"] += zoneStats.get("pumpTime", 0)
                aggregated[zoneNumStr]["runTime"] += zoneStats.get("runTime", 0)

    # Loop over DAYS_EMAIL but in reversed order until we meet min time requirement. This is the current burn rate
    for ts, record in sorted_summary_items[
        : -(cfg.water_monitor.days_email_report * cfg.water_monitor.logrotate_per_day) : -1
    ]:
        zonesStats = record["zonesStats"]
        lastEndTime = lastEndTime or record["logEndTime"]
        if aggregatedToggles < cfg.water_monitor.pump_toggles_count:
            aggregatedToggles += record.get("totalToggles", 0)
            aggregatedPumpTime += record.get("totalPumpTime", 0)
        for zoneNumStr, zoneStats in zonesStats.items():
            latestZoneStats = latest[zoneNumStr]
            zoneStats.get("pumpRate", 0)
            pumpTime = zoneStats.get("pumpTime", 0)
            runTime = zoneStats.get("runTime", 0)
            if latestZoneStats["zoneName"] is None:
                latestZoneStats["startEpoch"] = record["logStartEpoch"]
                latestZoneStats["zoneName"] = zoneStats.get("zoneName", "UNK")
            if not meetsMinRunTime(latestZoneStats["zoneName"], latestZoneStats["runTime"]):
                latestZoneStats["pumpTime"] += pumpTime
                latestZoneStats["runTime"] += runTime
                latestZoneStats["pumpRate"] = (
                    latestZoneStats["pumpTime"] / latestZoneStats["runTime"]
                )

    # Return a summary message.
    message = (
        '<html><head><link href="favicon.ico"/><title>Eden Monitoring Systems (TM)</title><style>'
    )
    message += """
  th {
    background-color: black;
    text-align: center;
    color: white;
  }
  th, td {
    padding: 1px 15px;
  }
  tr:nth-child(even) {
    background-color: #eee;
  }
  tr:nth-child(odd) {
    background-color: #fff;
  }
"""
    message += "</style></head><body>\n"
    message += (
        '<a href="http://%s/WaterParser_html/pump_rates.html">Water Charts</a>\n<br><br><table>\n'
        % cfg.my_external_ip
    )
    message += "<tr><th>Last Update</th><th>Zone</th><th>Status</th><th>Deviation</th><th>Rate</th><th>Minutes</th><th>Usage</th></tr>"

    for zoneNumStr, zoneStats in sorted(latest.items(), key=custom_sort):
        if aggregated[zoneNumStr]["pumpTime"] == 0 or aggregated[zoneNumStr]["runTime"] == 0:
            average = 0
            deviation = 0
        else:
            average = aggregated[zoneNumStr]["pumpTime"] / aggregated[zoneNumStr]["runTime"]
            deviation = (zoneStats["pumpRate"] - average) * 100 / average

        if not meetsMinRunTime(zoneStats["zoneName"], zoneStats["runTime"]):
            if zoneStats["pumpRate"] < average * cfg.water_monitor.alert_thresh:
                attrib = "Good."
            else:
                attrib = '<font color="blue">Low data</font>'
        else:
            if zoneStats["pumpRate"] < average * cfg.water_monitor.alert_thresh:
                attrib = "Good"
            else:
                attrib = '<b><font color="red">Failed</font></b>'

        date_brief = time.strftime("%m-%d", time.localtime(zoneStats["startEpoch"]))
        message += "<tr><td>[%s]</td><td>%s</td><td>%s</td>" % (
            date_brief,
            zoneStats["zoneName"],
            attrib,
        )
        message += '<td align="right">%+3d %%</td><td>%0.03f</td><td align="right">%4d</td>' % (
            deviation,
            zoneStats["pumpRate"],
            zoneStats["runTime"] / 60,
        )
        message += '<td align="right">%3d</td></tr>\n' % zoneStats["pumpTime"]

    pumpDutyCycle = aggregatedPumpTime / aggregatedToggles if aggregatedToggles else 0
    message += "</table><br>Pump duty cycle %s= <b>%d</b> seconds" % (
        '<font color="red">[Failed: Too Low] </font>'
        if pumpDutyCycle < cfg.water_monitor.pump_alert
        else "",
        pumpDutyCycle,
    )
    message += "<br><hr><br><small>Deviation alert @ %+d %%</small>" % (
        cfg.water_monitor.alert_thresh * 100 - 100
    )
    message += "<br><small>Pump alert @ %d seconds</small>" % (cfg.water_monitor.pump_alert)
    message += "<br><small>Last Update: %s</small>" % lastEndTime
    message += (
        '<br><small><a href="http://%s/reboot_foscam.php">Reboot Foscams</a></small>\n'
        % cfg.my_external_ip
    )

    message += "</body></html>"
    logging.info(message)
    with open("%s/html/report.html" % THIS_SCRIPT_DIR, "w+") as fp:
        fp.write(message)
    alert = True if "fail" in message.lower() else False
    if always_email:
        # Too many alerts, so use the always_email flag to gate email updates
        Mailer.sendmail("[PumpStats]", alert, message, always_email)


# Hacky: Assumes only drip zones have "D" in 1st half of zoneName
def meetsMinRunTime(zoneName, runTime):
    if "D" in zoneName.split("-")[0] and runTime > cfg.water_monitor.min_drip_zone_alert_time:
        return True
    elif (
        "S" in zoneName.split("-")[0] and runTime > cfg.water_monitor.min_sprinkler_zone_alert_time
    ):
        return True
    elif runTime > cfg.water_monitor.min_misc_zone_alert_time:
        return True
    return False
