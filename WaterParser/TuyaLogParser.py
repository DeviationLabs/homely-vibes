#!/usr/bin/env python3
import collections
import csv
from enum import Enum
import json
import logging
from lib import Mailer


class TuyaLogParser:
    ON_CURRENT_THRESH = 300

    def __init__(self, csvLogfile, jsonSummaryFile, isMostRecentLog):
        self.totalToggles = 0
        self.interStartMin = float("inf")
        self.totalPumpTime = 0
        self.logErrors = 0
        self.logStartEpoch = None
        self.logEndEpoch = None
        self.logStartTime = None
        self.logEndTime = None
        self.zonesStats = collections.defaultdict(
            lambda: {
                "zoneName": "",
                "startEpochs": [],
                "endEpochs": [],
                "isOff": True,
                "pumpRate": float("nan"),
                "pumpTime": 0,
                "runTime": 0,
                "toggles": 0,
            }
        )
        # Analyze the new log and update summary.json
        self.analyzeCsv(csvLogfile, isMostRecentLog)
        self.writeSummaryFile(jsonSummaryFile)

    def analyzeCsv(self, csvLogfile, isMostRecentLog):
        dataPoints, self.logErrors = loadCsv(csvLogfile)
        if len(dataPoints) == 0:
            logging.error("Warn: No records in file %s. Ignoring..." % csvLogfile)
            if isMostRecentLog:
                Mailer.sendmail(
                    "[PumpStats]", alert=True, message="Log file empty. Polling issue"
                )
            return

        self.logStartTime = fetch(dataPoints[0], "TIME")
        self.logStartEpoch = fetch(dataPoints[0], "EPOCH", "int")
        self.logEndTime = fetch(dataPoints[-1], "TIME")
        self.logEndEpoch = fetch(dataPoints[-1], "EPOCH", "int")
        fetch(dataPoints[0], "EPOCH", "int")
        prevEpoch = None
        prevZoneNum = None
        prevZoneStats = None
        interStartTime = float("inf")

        # If the most recent datapoint has error values then alert.
        if (
            fetch(dataPoints[-1], "CURRENT", "int") < 0
            or fetch(dataPoints[-1], "ZONE_NUM", "int") < -1
        ) and isMostRecentLog:
            msg = "Warning: Data logging failure during polling at %s.\n%s\n" % (
                self.logEndTime,
                " ".join(dataPoints[-1]),
            )
            if fetch(dataPoints[-1], "CURRENT", "int") < 0:
                msg += (
                    "Recommended Action: Manually power cycle the Tuya switch for pump"
                )
            elif fetch(dataPoints[-1], "ZONE_NUM", "int") < -1:
                msg += "Recommended Action: Check if Rachio online from iOS app"
            logging.warning(msg)
            Mailer.sendmail("[PumpStats]", alert=True, message=msg)

        for record in dataPoints:
            try:
                currEpoch = fetch(record, "EPOCH", "int")
                currValue = fetch(record, "CURRENT", "int")
                currZoneNum = fetch(record, "ZONE_NUM", "int")
                currZoneStats = self.zonesStats[currZoneNum]
                currZoneStats["zoneName"] = fetch(record, "ZONE_NAME")

                if currZoneNum != prevZoneNum:
                    currZoneStats["startEpochs"].append(currEpoch)
                    if prevZoneNum is not None:
                        prevZoneStats["endEpochs"].append(currEpoch)
                        prevZoneStats["isOff"] = True

                if prevEpoch is not None:
                    currZoneStats["runTime"] += currEpoch - prevEpoch
                    if not currZoneStats["isOff"]:
                        self.totalPumpTime += currEpoch - prevEpoch
                        currZoneStats["pumpTime"] += currEpoch - prevEpoch
                        interStartTime = 0
                    if currZoneStats["isOff"]:
                        interStartTime += currEpoch - prevEpoch

                if currValue > self.ON_CURRENT_THRESH and currZoneStats["isOff"]:
                    currZoneStats["isOff"] = False
                    self.interStartMin = min(self.interStartMin, interStartTime)
                    self.totalToggles += 1
                    currZoneStats["toggles"] += 1
                elif currValue < self.ON_CURRENT_THRESH and not currZoneStats["isOff"]:
                    currZoneStats["isOff"] = True

                prevZoneStats = currZoneStats
                prevZoneNum = currZoneNum
                prevEpoch = currEpoch
            except IndexError:
                logging.info(
                    "Failed to parse record: %s in file %s" % (record, self.csvLogfile)
                )

        # Done looping through the file. Now compute average pumpRate in this window
        for zoneNum, zone in self.zonesStats.items():
            if zone["runTime"] > 0:
                zone["pumpRate"] = float("%.04f" % (zone["pumpTime"] / zone["runTime"]))

        # Debug
        self.printLogStats(csvLogfile)

    def writeSummaryFile(self, jsonSummaryFile):
        if len(self.zonesStats) <= 0:
            return

        summary = collections.defaultdict()
        try:
            summary = readSummaryFile(jsonSummaryFile)
        except (OSError, ValueError):
            logging.warning("Warn: Failed to read old JSON file. Discarding ..")

        summary[self.logStartTime] = self.__dict__
        with open(jsonSummaryFile, "w") as fp:
            fp.write(json.dumps(summary, sort_keys=True, indent=2))

    # User debug, pretty print some stats per log file processed
    def printLogStats(csvLog, csvLogfile):
        if len(csvLog.zonesStats) < 1:
            return  # No Data

        logStartDate = csvLog.logStartTime[0:10]
        title = "{}   {} :: {} to {} [File Errors: {}]".format(
            csvLogfile,
            logStartDate[5:],
            csvLog.logStartTime[11:16],
            csvLog.logEndTime[11:16],
            csvLog.logErrors,
        )
        logging.info(title)

        for zoneNum, zone in csvLog.zonesStats.items():
            logging.info(
                "%25s - Toggles: %2d PumpTime: %s TotalTime: %s Rate: %.02f"
                % (
                    zone["zoneName"],
                    zone["toggles"],
                    ("%2d:%02d" % divmod(zone["pumpTime"], 60)),
                    ("%3d:%02d" % divmod(zone["runTime"], 60)),
                    zone["pumpRate"],
                )
            )


###################
##### Helpers #####
###################


# From a csv line record, fetch the column in TuyaLogCols and validate
class TuyaLogCols(Enum):
    EPOCH = 1
    TIME = 0
    CURRENT = 2
    ZONE_NUM = 3
    ZONE_NAME = 4


def fetch(record, enumVal, type=""):
    index = TuyaLogCols[enumVal].value
    val = record[index]
    if type == "int":
        try:
            val = int(val)
        except ValueError:
            val = -4
    return val


def loadCsv(csvLogfile):
    dataPoints = []
    logErrors = 0
    try:
        with open(csvLogfile, "r", encoding="utf-8", errors="replace") as csv_file:
            csvReader = csv.reader(
                (x.replace("\0", "") for x in csv_file), delimiter=","
            )
            for record in csvReader:
                if len(record) == len(TuyaLogCols):
                    dataPoints.append(record)
                else:
                    logErrors += 1
    except IOError:
        logging.warning("Warn: Failed to load file: %s. Ignoring..." % csvLogfile)
    return [dataPoints, logErrors]


def readSummaryFile(jsonSummaryFile):
    with open(jsonSummaryFile) as fp:
        summary = json.load(fp)
    return summary
