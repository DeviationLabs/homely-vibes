#!/usr/bin/env python3
from enum import Enum
import collections
import json
import logging
import time
import subprocess
from lib.config import get_config
import TuyaLogParser


# Poll data is very coarse. Let's refine using event log.
def patchWithRachioEvents():
    cfg = get_config()
    returnedOutput = subprocess.check_output(cfg.paths.rachio_events_cmd)

    rachioEvents = []
    # using decode() function to convert byte string to string
    for line in returnedOutput.decode("utf-8").splitlines():
        row = line.split(",")
        rachioEvents.append(row)
    rachioEvents.append([0, False, "Dummy"])  # A dummy row to flush out the calculations

    summary = TuyaLogParser.readSummaryFile(cfg.paths.json_summary_file)
    eventNum = 0
    for ts, record in sorted(summary.items(), reverse=False):
        zonesModified = collections.defaultdict(
            lambda: {
                "touched": False,
                "fallbackStartEpoch": [record["logStartEpoch"]],
                "fallbackEndEpoch": [record["logEndEpoch"]],
                "isOff": True,
            }
        )
        while eventNum < len(rachioEvents):
            event = rachioEvents[eventNum]
            eventEpoch = fetch(event, "EPOCH", "int")
            eventZoneActive = fetch(event, "ACTIVE", "bool")
            eventZoneSubstr = fetch(event, "ZONE_SUBSTR")

            if record["logStartEpoch"] < eventEpoch < record["logEndEpoch"]:
                # We only have partial zone name, so loop over all zones
                # to figure out which one this is.
                for zoneNum, zoneStats in record["zonesStats"].items():
                    thisZoneModified = zonesModified[zoneNum]

                    if eventZoneSubstr not in zoneStats["zoneName"]:
                        # Not this zone. Try the next
                        continue
                    if not thisZoneModified["touched"] and not eventZoneActive:
                        logging.warning(
                            "Warning: Ahh...Found off before on (%s: zone %s). Ignore"
                            % (zoneStats["zoneName"], record["logStartTime"])
                        )
                        continue

                    if not thisZoneModified["touched"]:
                        ## Ahha. Found a new zone that needs fixing. Reset key stats.
                        thisZoneModified["touched"] = True
                        # Fallback stats are tricky, we use the available data and fallback only if required.
                        thisZoneModified["fallbackStartEpoch"][0:0] = zoneStats["startEpochs"]
                        thisZoneModified["fallbackEndEpoch"][0:0] = zoneStats["endEpochs"]
                        zoneStats["startEpochs"] = []
                        zoneStats["endEpochs"] = []
                        zoneStats["runTime"] = 0
                    if eventZoneActive is True:
                        zoneStats["startEpochs"].append(eventEpoch)
                        if len(thisZoneModified["fallbackStartEpoch"]) > 1:
                            # Found sth better than fallback, but never pop out the last one.
                            thisZoneModified["fallbackStartEpoch"].pop(0)
                    else:
                        if zoneStats["startEpochs"] is None:
                            zoneStats["startEpochs"] = thisZoneModified["fallbackStartEpoch"][0]
                        zoneStats["endEpochs"].append(eventEpoch)
                        if len(thisZoneModified["fallbackEndEpoch"]) > 1:
                            # Never pop out the last one.
                            thisZoneModified["fallbackEndEpoch"].pop(0)
                eventNum += 1
            else:
                if eventEpoch < record["logStartEpoch"]:
                    # Didn't find log for this event. Discard event
                    eventNum += 1
                if not any(zonesModified.items()):
                    break  # Optimization - expedite my exit

                # Fix all calculations, then move to next log
                for zoneNum, zoneStats in record["zonesStats"].items():
                    thisZoneModified = zonesModified[zoneNum]
                    if thisZoneModified["touched"]:
                        #            print("We patched this log:zone %s:%s" % (record['logStartTime'], zoneNum))
                        for idx in range(len(zoneStats["startEpochs"])):
                            while not len(zoneStats["endEpochs"]) > idx:
                                zoneStats["endEpochs"].append(
                                    thisZoneModified["fallbackEndEpoch"][0]
                                )
                            zoneStats["runTime"] += (
                                zoneStats["endEpochs"][idx] - zoneStats["startEpochs"][idx]
                            )
                            zoneStats["pumpRate"] = float(
                                "%.04f" % (zoneStats["pumpTime"] / zoneStats["runTime"])
                            )
                break

    with open(cfg.paths.json_summary_patch_file, "w") as fp:
        fp.write(json.dumps(summary, sort_keys=True, indent=2))


# Preprocess a PumpStats file from Summary. Keep only N days
def writeFromSummary():
    cfg = get_config()
    currEpoch = int(time.time())
    zonesHistory = collections.defaultdict(
        lambda: {"zoneName": None, "pumpRates": [], "runTimes": []}
    )

    summary = TuyaLogParser.readSummaryFile(cfg.paths.json_summary_patch_file)
    logging.info(
        "Found %s records, looking back %s days..."
        % (len(summary), cfg.water_monitor.days_lookback)
    )

    for ts, record in sorted(summary.items(), reverse=False):
        if record["logStartEpoch"] < cfg.water_monitor.start_from_epoch:
            continue
        if (
            currEpoch - record["logStartEpoch"]
        ) > cfg.water_monitor.days_lookback * cfg.seconds_in_day:
            continue

        zonesStats = record["zonesStats"]
        for zoneNum in range(
            -1, cfg.water_monitor.max_zones
        ):  # Don't care about UNK and RateLimited
            zoneNumStr = str(zoneNum)
            zone = {}
            if zonesStats.get(zoneNumStr, None) is not None:
                zone = zonesStats[zoneNumStr]
                zonesHistory[zoneNumStr]["zoneName"] = zone["zoneName"]
            pumpRate = zone.get("pumpRate", None)
            runTime = zone.get("runTime", None)
            # Get rid of the low confidence data when drip runs for too little time
            if runTime is None:
                #          or ( 'D' in zone['zoneName'].split('-')[0] and runTime < cfg.water_monitor.min_drip_plot_time):
                pumpRate = None
            # DST and other confounding issues. Put an upper bound on runTime
            if runTime is not None:
                maxSecs = int(cfg.seconds_in_day / cfg.water_monitor.logrotate_per_day)
                runTime = min(runTime, maxSecs)
            zonesHistory[zoneNumStr]["pumpRates"].append({"label": ts, "y": pumpRate})
            zonesHistory[zoneNumStr]["runTimes"].append({"label": ts, "y": runTime})
    # Drop reference to junk zones and save
    for zoneNum in range(-3, cfg.water_monitor.max_zones):
        zoneNumStr = str(zoneNum)
        if zonesHistory[zoneNumStr]["zoneName"] is None:
            del zonesHistory[zoneNumStr]
            continue
    #  printPumpStats(zonesHistory)
    with open(cfg.paths.json_pumprates_file, "w") as fp:
        fp.write(json.dumps(zonesHistory, sort_keys=True, indent=2))
    logging.info("Done and saved to %s" % cfg.paths.json_pumprates_file)


# Pretty print the pump stats
def printPumpStats(zonesHistory):
    cfg = get_config()
    for zoneNum in range(-3, cfg.water_monitor.max_zones):
        zoneNumStr = str(zoneNum)
        zoneHistory = zonesHistory.get(zoneNumStr, None)
        if zoneHistory is None:
            continue
        zoneName = zoneHistory["zoneName"]
        logging.debug("Data for: %s" % zoneName)

        zoneRates = zoneHistory["pumpRates"]
        zoneRuntimes = zoneHistory["runTimes"]
        for idx in range(len(zoneRates)):
            if zoneRates[idx]["y"] is not None and zoneRuntimes[idx]["y"] is not None:
                logging.info(
                    "%15s: %.03f , %4d"
                    % (
                        zoneRates[idx]["label"],
                        zoneRates[idx]["y"],
                        zoneRuntimes[idx]["y"],
                    )
                )


# From a csv line record, fetch the column in RachioEventCols and validate
class RachioEventCols(Enum):
    EPOCH = 0
    ACTIVE = 1
    ZONE_SUBSTR = 2


def fetch(record, enumVal, type=""):
    index = RachioEventCols[enumVal].value
    val = record[index]
    if type == "int":
        try:
            val = int(val)
        except ValueError:
            val = 0
    elif type == "bool":
        val = val in ["true", "1", "t", "y", "yes", "True"]
    return val
