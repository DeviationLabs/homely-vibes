#!/usr/bin/env node

const RachioClient = require('rachio');
const MY_API_KEY = process.env.RACHIO_API_KEY;
const DEVICE_ID = process.env.RACHIO_ID;
const client = new RachioClient(MY_API_KEY);

/* WARNING = 1700 calls/day rate limiter on Rachio */
client.getDevice(DEVICE_ID)
  .then(device => device.getActiveZone())
  .then(activeZone =>
          console.log(activeZone
                      ? `${activeZone.zoneNumber},${activeZone.name}`
                      : "-1,In House")
       )
  .catch(() => console.log(`-2,Rachio Error`));
//  .then(activeZone => console.log(activeZone));
