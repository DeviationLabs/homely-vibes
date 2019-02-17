#!/usr/bin/env python3.6
import collections
import csv
from enum import Enum
import json
import logging
import os
import time
import Constants
import Mailer

class TuyaLogParser:
  ON_CURRENT_THRESH = 300

  def __init__(self, csvLogfile, jsonSummaryFile):
    self.email_errors = True # TODO: Feeble attempt to prevent a flood of email notifications.
    self.totalToggles = 0
    self.interStartMin = float('inf')
    self.totalPumpTime = 0
    self.logErrors = 0
    self.logStartEpoch = None
    self.logEndEpoch = None
    self.logStartTime = None
    self.logEndTime = None
    self.zonesStats = collections.defaultdict(lambda: {
                                               'zoneName' : '',
                                               'startEpochs' : [],
                                               'endEpochs' : [],
                                               'isOff' : True,
                                               'pumpRate' : float('nan'),
                                               'pumpTime': 0,
                                               'runTime' : 0,
                                               'toggles' : 0,
                                             })
    # Analyze the new log and update summary.json
    self.analyzeCsv(csvLogfile)
    self.writeSummaryFile(jsonSummaryFile)


  def analyzeCsv(self, csvLogfile):
    dataPoints, self.logErrors = loadCsv(csvLogfile)
    if (len(dataPoints) == 0):
      logging.error("Warn: No records in file %s. Ignoring..." % csvLogfile)
      Mailer.sendmail("[PumpStats]", alert=True, message="Log file empty. Polling issue", \
                      always_email=self.email_errors)
      self.email_errors = False
      return

    self.logStartTime = fetch(dataPoints[0], 'TIME')
    self.logStartEpoch = fetch(dataPoints[0], 'EPOCH', 'int')
    self.logEndTime = fetch(dataPoints[-1], 'TIME')
    self.logEndEpoch = fetch(dataPoints[-1], 'EPOCH', 'int')
    lastStartTime = fetch(dataPoints[0], 'EPOCH', 'int')
    prevEpoch = None
    prevZoneNum = None
    prevZoneStats = None
    interStartTime = float('inf')

    # If the most recent datapoint has error values (typically -2) then alert.
    if fetch(dataPoints[-1], 'CURRENT', 'int') < 0 or fetch(dataPoints[-1], 'ZONE_NUM', 'int') < -1:
      msg = "Warning: Data logging failure during polling at %s.\n%s" % (self.logEndTime, " ".join(dataPoints[-1]) )
      logging.warn(msg)
      Mailer.sendmail("[PumpStats]", alert=True, message=msg, always_email=self.email_errors)
      self.email_errors = False

    for record in dataPoints:
      try:
        currEpoch = fetch(record, 'EPOCH', 'int')
        currValue = fetch(record, 'CURRENT', 'int')
        currZoneNum = fetch(record, 'ZONE_NUM', 'int')
        currZoneStats = self.zonesStats[currZoneNum]
        currZoneStats['zoneName'] = fetch(record, 'ZONE_NAME')

        if (currZoneNum != prevZoneNum):
          currZoneStats['startEpochs'].append(currEpoch)
          if(prevZoneNum is not None):
            prevZoneStats['endEpochs'].append(currEpoch)
            prevZoneStats['isOff'] = True

        if prevEpoch is not None:
          currZoneStats['runTime'] += currEpoch - prevEpoch
          if not currZoneStats['isOff']:
            self.totalPumpTime += currEpoch - prevEpoch
            currZoneStats['pumpTime'] += currEpoch - prevEpoch
            interStartTime = 0
          if currZoneStats['isOff']:
            interStartTime += currEpoch - prevEpoch

        if (currValue > self.ON_CURRENT_THRESH and currZoneStats['isOff']):
          currZoneStats['isOff'] = False
          self.interStartMin = min(self.interStartMin, interStartTime)
          self.totalToggles += 1
          currZoneStats['toggles'] += 1
        elif (currValue < self.ON_CURRENT_THRESH and not currZoneStats['isOff']):
          currZoneStats['isOff'] = True

        prevZoneStats = currZoneStats
        prevZoneNum = currZoneNum
        prevEpoch = currEpoch
      except IndexError as e:
        logging.info("Failed to parse record: %s in file %s" % (record, self.csvLogfile))

    # Done looping through the file. Now compute average pumpRate in this window
    for zoneNum, zone in self.zonesStats.items():
      if (zone['runTime'] > 0):
        zone['pumpRate'] = float("%.04f" % (zone['pumpTime']/zone['runTime']))

    # Debug
    self.printLogStats(csvLogfile)


  def writeSummaryFile(self, jsonSummaryFile):
    if (len(self.zonesStats) <= 0):
      return

    summary = collections.defaultdict()
    try:
      summary = readSummaryFile(jsonSummaryFile)
    except:
      logging.warn('Warn: Failed to read old JSON file. Discarding ..')

    summary[self.logStartTime] = self.__dict__
    with open(jsonSummaryFile, 'w') as fp:
      fp.write(json.dumps(summary, sort_keys=True, indent=2))


  # User debug, pretty print some stats per log file processed
  def printLogStats(csvLog, csvLogfile):
    if (len(csvLog.zonesStats) < 1):
      return   # No Data

    logStartDate = csvLog.logStartTime[0:10]
    logStartDay = "" ## TODO: get day from startDate
    title = "{}   {} :: {} to {} [File Errors: {}]".format(
               csvLogfile, logStartDate[5:], csvLog.logStartTime[11:16],
               csvLog.logEndTime[11:16], csvLog.logErrors)
    logging.info(title)

    for zoneNum, zone in csvLog.zonesStats.items():
      logging.info("%25s - Toggles: %2d PumpTime: %s TotalTime: %s Rate: %.02f" %
              (zone['zoneName'], zone['toggles'],
               ("%2d:%02d" % divmod(zone['pumpTime'],60)),
               ("%3d:%02d" % divmod(zone['runTime'],60)),
               zone['pumpRate'])
           )


###################
##### Helpers #####
###################

# From a csv line record, fetch the column in TuyaLogCols and validate
class TuyaLogCols(Enum):
  EPOCH     = 1
  TIME      = 0
  CURRENT   = 2
  ZONE_NUM  = 3
  ZONE_NAME = 4
def fetch(record, enumVal, type = ''):
  index = TuyaLogCols[enumVal].value
  val = record[index]
  if (type == 'int'):
    try:
      val = int(val)
    except:
      val = -4
  return val


def loadCsv(csvLogfile):
  dataPoints = []
  logErrors = 0
  try:
    with open(csvLogfile, 'r', encoding='utf-8', errors='replace') as csv_file:
      csvReader = csv.reader((x.replace('\0','') for x in csv_file), delimiter=',')
      for record in csvReader:
        if (len(record) == len(TuyaLogCols)):
          dataPoints.append(record)
        else:
          logErrors += 1
  except IOError as e:
    logging.warn("Warn: Failed to load file: %s. Ignoring..." % csvLogfile)
  return [dataPoints, logErrors]


def readSummaryFile(jsonSummaryFile):
  with open(jsonSummaryFile) as fp:
    summary = json.load(fp)
  return summary


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
  lastEndTime = None

  for ts, record in list(summary.items())[-(Constants.DAYS_LOOKBACK*Constants.LOGROTATE_PER_DAY):]:
    zonesStats = record['zonesStats']
    lastEndTime = record['logEndTime']
    for zoneNumStr, zoneStats in zonesStats.items():
      aggregated[zoneNumStr]['pumpTime'] += zoneStats.get('pumpTime', 0)
      aggregated[zoneNumStr]['runTime'] += zoneStats.get('runTime', 0)

  # Loop over DAYS_EMAIL but in reversed order until we meet min time requirement
  for ts, record in list(summary.items())[:-(Constants.DAYS_EMAIL_REPORT*Constants.LOGROTATE_PER_DAY):-1]:
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
  message = "<html><head><style>"
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
  message += "<a href=\"http://%s/WaterMonitoring_html/\">Dashboard</a>\n<br><br><table>\n" % Constants.MY_EXTERNAL_IP
  message += "<tr><th>Date</th><th>Zone</th><th>Status</th><th>Deviation</th><th>Rate</th><th>Minutes</th></tr>"

  for zoneNumStr, zoneStats in sorted(latest.items()):
    average = aggregated[zoneNumStr]['pumpTime'] / aggregated[zoneNumStr]['runTime']

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
                % ( (zoneStats['pumpRate'] - average) * 100 / average,\
                    zoneStats['pumpRate'],\
                    zoneStats['runTime']/60 )

  pumpDutyCycle = aggregatedPumpTime / aggregatedToggles
  message += "</table><br>Pump duty cycle %s= <b>%d</b> seconds" % \
              ("<font color=\"red\">[Failed: Too Low] </font>" if pumpDutyCycle < Constants.PUMP_ALERT else "",
              pumpDutyCycle)
  message += "<br><hr><br><small>Deviation alert @ %+d %%</small>" % (Constants.ALERT_THRESH * 100 - 100)
  message += "<br><small>Pump alert @ %d seconds</small>" % (Constants.PUMP_ALERT)
  message += "<br><small>Last Update: %s</small>" % lastEndTime

  message += "</body></html>"
  logging.info(message)
  with open("%s/public_html/report.html" % Constants.HOME,'w') as fp:
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

