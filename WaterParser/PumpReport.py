#!/usr/bin/env python3.6
import collections
import logging
import os
import time
import Constants
import Mailer
from TuyaLogParser import readSummaryFile

THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Flag all zone where latest rate is greater than average of the last N days.
def genSendMessage(always_email):
  aggregated = collections.defaultdict(lambda: {'pumpTime': 0,
                                                'runTime': 0 })
  latest = collections.defaultdict(lambda: {'pumpTime': 0,
                                            'pumpRate': 0,
                                            'runTime': 0,
                                            'zoneName': None,
                                            'startEpoch': 0 })
  aggregatedPumpTime = 0
  aggregatedToggles = 0
  summary = readSummaryFile(Constants.JSON_SUMMARY_PATCH_FILE)
  sorted_summary_items = sorted(list(summary.items()))
  lastEndTime = None

  for ts, record in sorted_summary_items[-(Constants.DAYS_LOOKBACK*Constants.LOGROTATE_PER_DAY):]:
    zonesStats = record['zonesStats']
    lastEndTime = record['logEndTime']
    for zoneNumStr, zoneStats in zonesStats.items():
      aggregated[zoneNumStr]['pumpTime'] += zoneStats.get('pumpTime', 0)
      aggregated[zoneNumStr]['runTime'] += zoneStats.get('runTime', 0)

  # Loop over DAYS_EMAIL but in reversed order until we meet min time requirement
  for ts, record in sorted_summary_items[:-(Constants.DAYS_EMAIL_REPORT*Constants.LOGROTATE_PER_DAY):-1]:
    zonesStats = record['zonesStats']
    if aggregatedToggles < Constants.PUMP_TOGGLES_COUNT:
      aggregatedToggles += record.get('totalToggles', 0)
      aggregatedPumpTime += record.get('totalPumpTime', 0)
    for zoneNumStr, zoneStats in zonesStats.items():
      latestZoneStats = latest[zoneNumStr]
      pumpRate = zoneStats.get('pumpRate', 0)
      pumpTime = zoneStats.get('pumpTime', 0)
      runTime = zoneStats.get('runTime', 0)
      if latestZoneStats['zoneName'] is None:
        latestZoneStats['startEpoch'] = record['logStartEpoch']
        latestZoneStats['zoneName'] = zoneStats.get('zoneName',"UNK")
      if not meetsMinRunTime(latestZoneStats['zoneName'], latestZoneStats['runTime']):
        latestZoneStats['pumpTime'] += pumpTime
        latestZoneStats['runTime'] += runTime
        latestZoneStats['pumpRate'] = latestZoneStats['pumpTime'] / latestZoneStats['runTime']

  # Return a summary message.
  message = "<html><head><link href=\"favicon.ico\"/><title>Summary Stats</title><style>"
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
  message += "<a href=\"http://%s/WaterParser_html/pump_rates.html\">Charts</a>\n<br><br><table>\n" % Constants.MY_EXTERNAL_IP
  message += "<tr><th>Last Update</th><th>Zone</th><th>Status</th><th>Deviation</th><th>Rate</th><th>Minutes</th></tr>"

  for zoneNumStr, zoneStats in sorted(latest.items()):
    if aggregated[zoneNumStr]['pumpTime'] == 0 or aggregated[zoneNumStr]['runTime'] == 0:
      average = 0
      deviation = 0
    else:
      average = aggregated[zoneNumStr]['pumpTime'] / aggregated[zoneNumStr]['runTime']
      deviation = (zoneStats['pumpRate'] - average) * 100 / average

    if not meetsMinRunTime(zoneStats['zoneName'], zoneStats['runTime']):
      if zoneStats['pumpRate'] < average * Constants.ALERT_THRESH:
        attrib = "Good."
      else:
        attrib = "<font color=\"blue\">Low data</font>"
    else:
      if zoneStats['pumpRate'] < average * Constants.ALERT_THRESH:
        attrib = "Good"
      else:
        attrib = "<b><font color=\"red\">Failed</font></b>"
    date_brief = time.strftime('%m-%d', time.localtime(zoneStats['startEpoch']))
    message += "<tr><td>[%s]</td><td>%s</td><td>%s</td>" % (date_brief, zoneStats['zoneName'], attrib)

    message +=  "<td align=\"right\">%+3d %%</td><td>%0.03f</td><td align=\"right\">%4d</td></tr>\n" \
                % ( deviation, zoneStats['pumpRate'], zoneStats['runTime']/60 )

  pumpDutyCycle = aggregatedPumpTime / aggregatedToggles
  message += "</table><br>Pump duty cycle %s= <b>%d</b> seconds" % \
              ("<font color=\"red\">[Failed: Too Low] </font>" if pumpDutyCycle < Constants.PUMP_ALERT else "",
              pumpDutyCycle)
  message += "<br><hr><br><small>Deviation alert @ %+d %%</small>" % (Constants.ALERT_THRESH * 100 - 100)
  message += "<br><small>Pump alert @ %d seconds</small>" % (Constants.PUMP_ALERT)
  message += "<br><small>Last Update: %s</small>" % lastEndTime

  message += "</body></html>"
  logging.info(message)
  with open("%s/html/report.html" % THIS_SCRIPT_DIR ,'w+') as fp:
    fp.write(message)
  alert = True if "fail" in message.lower() else False
  if always_email:
    # Too many alerts, so use the always_email flag to gate email updates
    Mailer.sendmail("[PumpStats]", alert, message, always_email)


# Hacky: Assumes only drip zones have "D" in 1st half of zoneName
def meetsMinRunTime(zoneName, runTime):
  if ('D' in zoneName.split('-')[0] and runTime > Constants.MIN_DRIP_ZONE_ALERT_TIME):
    return True
  elif ('S' in zoneName.split('-')[0] and runTime > Constants.MIN_SPRINKLER_ZONE_ALERT_TIME):
    return True
  elif (runTime > Constants.MIN_MISC_ZONE_ALERT_TIME):
    return True
  return False


