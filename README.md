# water-tracking
IoT integration between Tuya smart switch and Rach.io irrigation control to track and alert on water consumption

Project Timelines:

* 08-10-2018: Concept
* 08-22-2018: Buy Energy Monitors
* 08-25-2018: Energy Monitor cli scraper tested
* 08-28-2018: cli scraper enhancements to get power readings
* 08-30-2018: [v0.1] simple script to get csv logs of scrape, with 3 step manual excel plots.
* 09-03-2018: [v0.5] 1st online plot with canvasJS on apache server
* 09-10-2018: [v0.6] Harden: autostart, crontabs, etc.
* 09-20-2018: [v0.8] Plot histogram data. Looks good but not actionable. "May help find a leak"
* 10-06-2018: [v0.9] Build rachio cli scraper. Plot rachio data. We now have full visibility on what is going on!
              Actionable but not easy to understand. "Will help find a leak"
* ...
* 10-25-2018: [v1.0] Plot "rates"! Actionable, easy to understand, but not accurate. "Will find leaks, but also high FA/MD"
* 11-01-2018: Build rachio event parser
* 11-04-2018: [v1.1] Move to event parsing. "Definitive", but reactive.
* 11-06-2018: [v1.1.1] Better handling of missing events.
* 11-09-2018: [v1.2] Emails. "Definitive with Reminders". Quick hack emails. Dropped the dummy zonestats.
              Fix events handling for missing start event, or partial irrigation data by always starting RachioEvents reader from midnight.
* 11-16-2018: [v1.2.1] Refactor. Drop the low confidence data from short runs for Drip zones
* 11-17-2018: [v1.3] Email alerts - 1st version. Seems to be about right, but will need tweaking. "Definitive and proactive"
* 11-21-2018: [v1.3.1] Refactor emails. Better handling of alerting, email frequency, content
* 12-08-2018: [v1.4] Extend email capabilties. Add Foscam/Alpha monitoring to ecosystem. Refactor directories
* 12-08-2018: [v1.4.1] use logger and arg parser in Parser. Remove symlink to lib files
* 01-15-2019: [v1.4.2] Github repo. move to eden for email credentials.

--

Future:

* Move out all hardcoded config in all files - JS and that yucky shell script
* Pump duty cycle alerting. Extend pump avg to be last 10 minutes/ last 30 days.
* remove hardcoding in JS files into config store. Add files to repo.
* Alpha up check detailed.

--

Modules:

wget -c https://nodejs.org/dist/latest-v10.x/node-v10.9.0-linux-arm64.tar.gz
sudo tar -xzf node-v10.9.0-linux-arm64.tar.gz --strip-components=1 --group=root --no-same-owner -C /usr/local/
apt-get install npm

https://github.com/TuyaAPI/cli
https://github.com/codetheweb/tuyapi
sudo npm -g i rachio
sudo npm -g i foscam

Changes:

* In cli, modify get to passthrough config. Add support for dps option
* In tuyaApi, add support for dps option

