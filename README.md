# water-tracking and other IoT automata
Primary function:
IoT integration between Tuya smart switch and Rach.io irrigation control to track and alert on water consumption
* Poll data from Tuya and Rach.io
* Postprocessing to understand usage
* Http service for plotting data
* Email monitoring if current (short term filtered) rates exceed historical rates

Secondary function:
Simple script for monitoring Foscam IP cameras and Windows desktop, and reboot on demand with email reporting. Also manage ftp folder.

Ternary (still in experimentation):
Image classifier for garage door status with email reporting

Project Timelines:
* 08-10-2018: Initial concept for water-monitoring after n-th breakage of drip irrigation and many days of wasted water.
* 08-22-2018: Buy smart switches with energy monitoring (aka: Tuya)
* 08-25-2018: Energy monitor cli scraper tested
* 08-28-2018: Enhancements to tuya-cli to get electric current readings
* 08-30-2018: [v0.1]   Simple script to get csv logs of scrape, with a 3 step manual process to generate MS Excel plots.
* 09-03-2018: [v0.5]   1st online plot with canvasJS on apache server. "We have live data on pump state"
* 09-10-2018: [v0.6]   Harden: autostart polling script, crontabs, etc.
* 09-20-2018: [v0.8]   Plot histogram data. Looks good but not actionable. "May help find a leak"
* 10-06-2018: [v0.9]   Build rachio cli scraper. Plot rachio data. We now have full visibility on what is going on!
                       Actionable but not easy to understand. "Will help find a leak"
* 10-25-2018: [v1.0]   Plot "rates"! Actionable, easy to understand, but not accurate. "Will find leaks, but also high FA/MD"
* 11-01-2018: [v1.0.1] Build rachio event parser
* 11-04-2018: [v1.1]   Move to event parsing. "Definitive", but reactive.
* 11-06-2018: [v1.1.1] Better handling of missing events.
* 11-09-2018: [v1.2]   Emails. "Definitive with Reminders". Quick hack emails. Dropped the dummy zonestats.
                       Fix events handling for missing start event, or partial irrigation data by always starting RachioEvents reader from midnight.
* 11-16-2018: [v1.2.1] Refactor. Drop the low confidence data from short runs for Drip zones
* 11-17-2018: [v1.3]   Email alerts - 1st version. Seems to be about right, but will need tweaking. "Definitive and proactive"
* 11-21-2018: [v1.3.1] Refactor emails. Better handling of alerting, email frequency, content
* 12-08-2018: [v1.4]   Extend email capabilties. Add Foscam/Alpha monitoring to ecosystem. Refactor directories
* 12-08-2018: [v1.4.1] Use logger and arg parser in Parser. Remove symlink to lib files
* 01-15-2019: [v1.4.2] Github repo.
* 01-15-2019: [v1.4.3] Better filtering on email reports. Add pumpDutyCycle to emails.
* 01-20-2019: [v1.4.4] Better reporting on reboot. Add deep inspection to confirm windows is healthy
* 01-21-2019: [v1.5.0] Foscam garage image fetch. ML experimentation stubs.
                       Further refinement on email reports (inc script error traceback)
* 01-23-2019: [v1.5.1] HTML emails. CPU temp monitoring for host OS. Foscam ftp folder sanity check

--

Future:
* Foscam ML garage door check.
* Add filtering to water monitor plots? (not needed?)
* Monitor foscam video feed storage on NAS

--

Dependencies:
* https://github.com/TuyaAPI/cli
* https://github.com/codetheweb/tuyapi
* wget -c https://nodejs.org/dist/latest-v10.x/node-v10.9.0-linux-arm64.tar.gz
* sudo tar -xzf node-v10.9.0-linux-arm64.tar.gz --strip-components=1 --group=root --no-same-owner -C /usr/local/
* apt-get install npm
* sudo npm -g i rachio
* sudo -H python3.6 -m pip install pyfoscam
* pip install tensorflow

Changes to libraries:
* In cli, modify get to passthrough config. Add support for dps option
* In tuyaApi, add support for dps option

