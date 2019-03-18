#!/usr/bin/env node

const RachioClient = require('rachio');

const MILLI_SEC_IN_DAY = 86400000;
const END_TIME = Date.now();
const START_TIME = (Math.floor(END_TIME/MILLI_SEC_IN_DAY) - 14) * MILLI_SEC_IN_DAY;
//const START_TIME = END_TIME - 86400000*3;  // For Debug

const MY_API_KEY = process.env.RACHIO_API_KEY;
const DEVICE_ID = process.env.RACHIO_ID;
const FILTERS = {
  type: 'ZONE_STATUS',
  topic: 'WATERING'
};

/* WARNING = 1700 calls/day rate limiter on Rachio */
const client = new RachioClient(MY_API_KEY);
client.getDeviceEvents(DEVICE_ID, START_TIME, END_TIME, FILTERS)
  .then(events => { events.forEach(event => {
//            console.log(event)
            var zoneNameSubstr = event.summary.split("-")[0];
            zoneNameSubstr = zoneNameSubstr.split("(")[0];  // legacy. Delete after 12-01-2018
            var eventEpoch = (event.eventDate/1000);
            if (event.subType.match(/ZONE_STARTED/g)) {
              console.log(`${eventEpoch},True,${zoneNameSubstr}`);
            }
            else if (event.subType.match(/ZONE_COMPLETED/g)
                || event.subType.match(/ZONE_STOPPED/g)) {
              console.log(`${eventEpoch},False,${zoneNameSubstr}`);
            }
          }
        )
      }
   )
  .catch(() => console.log(`${END_TIME},UNK,RateLimited`));
