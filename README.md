# water-tracking and other IoT automata
### Primary function:
IoT integration between Tuya smart switch and Rach.io irrigation control to track and alert on water consumption
* Poll data from Tuya and Rach.io
* Postprocessing to understand usage
* Http service for plotting data
* Email monitoring if current (short term filtered) rates exceed historical rates

### Secondary functions:
* Simple script for monitoring Foscam IP cameras and Windows desktop, and reboot on demand with email reporting.
* Manage log rotation on foscam videos ftp folder.
* Image classifier for garage door status with email reporting
* Test uplink for external IP address, and speedtest
* Monitor laptop "GARMOUGAL" for blacklisted websites

### Ternary functions:
* Add foscams to alexa via homebridge straddles.

## Project Timelines:
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
* 01-25-2019: [v1.5.2] HTML emails part 2. Minor tweak to averaging computation. Installation notes for tensorflow
* 01-28-2019: [v1.5.3] Minor tweaks on plotter/email. bug fix on check_deep_state. restartable background processes in cron.
* 01-30-2019: [v1.5.4] Minor fix in rates computation. Post report on the website too. bug fixes on check_garage. Drop the non-alert day.
* 02-13-2019: [v1.5.5] Maintenance release. TF libraries finally working (Details below).
* 02-14-2019: [v1.5.6] Some cleanup around email alerts
* 02-16-2019: [v1.5.7] Bug fix on node check, simplified Mailer logic -> move complexity into cron
                       New TF model training and predictor script (but still not working for garage image)
* 02-17-2019: [v1.6.0] First version of garage door detector (Recall: 0% :( )
                       Note: Need to run, and save transferlearning output before first activation
                       Moved everything down to python 3.5 to support TF.
* 02-17-2019: [v1.6.1] Bug fix on alerting exposed by python3.5 not using ordered dicts. Fix logger level.
                       Garage detector can now bypass image save to disk. Recall is still 0%. Install notes for OpenCV
* 02-18-2019: [v1.6.2] OpenCV only available for python3.6. In general seems to be a bad idea to stay with 3.5, as apt-get will misbehave.
                       Building TF for 3.6 and we expect cruising. Some cleanup - retry for nodecheck, config of "logs" directory.
* 02-19-2019: [v1.6.3] favicon. Better error reporting on purge_foscam_files. Opencv install notes. refactor PumpReports.
* 03-01-2019: [v1.6.4] Better sizing for charts. Stablize Garage TF on python3.5. Improvements to deletion of foscam logging directory
* 03-10-2019: [v1.6.5] Improvements to deletion of foscam logging directory. Add foscam image checking to Rebooter
* 03-16-2019: [v1.6.6] Bring foscam deletion under the proper email control (instead of using cron reports)
* 03-17-2019: [v1.6.7] Early Success on Garage ML! Worked on animals library...
```
    Loading model: /home/abutala/bin/GarageCheck/my_model.h5
    Recheck model on training dir: /home/abutala/image_classification/train_animals/
    Found 197 images belonging to 3 classes.
    Loss:  0.2567218820632998 Accuracy:  0.9187817258883249
    Predicting image: /home/abutala/image_classification/train_animals/horses/images.jpg
    1/1 [==============================] - 4s 4s/step
    Best Guess: horses (Confidence: 0.94)  -- [0.01,0.04,0.94]
```
* 03-18-2019: [v2.0.0] First working release of ML detector
* 02-16-2020: [v2.1.0] Add uplink test diagnostics
* 02-17-2020: [v2.1.1] Add reboot foscams to landing page. Refine stats sort order on landing page
* 03-22-2020: [v2.1.2] uplink test retry logic
* 04-25-2020: [v2.1.3] Rollup of minor enhancements to error handling
* 05-22-2020: [v2.2.0] New module for remote browser web usage alerting. Also add Twilio SMSing

### Pending:
* Eliminate Constants.sh using https://goo.gl/UgfwCr

## Dependencies:
* Base:
  * wget -c https://nodejs.org/dist/latest-v10.x/node-v10.9.0-linux-arm64.tar.gz
  * sudo tar -xzf node-v10.9.0-linux-arm64.tar.gz --strip-components=1 --group=root --no-same-owner -C /usr/local/
  * apt-get install npm
  * apt-get install python3.6 python3-pandas python3-numpy python3-scipy python3-keras python3-matplotlib python3-opencv python3-h5py python3-pip
  * Note: keras is a part of TF, but in order to support legacy code, we need the standalone package too.
* Tuya/Rachio/Foscam/Liftmaster:
  * https://github.com/TuyaAPI/cli
  * https://github.com/codetheweb/tuyapi
  * sudo npm -g i rachio
  * pip3 install pyfoscam
  * pip3 install pymyq
* bazel-- modify scripts/bootstrap/compile.sh with .. BAZEL_JAVAC_OPTS="-J-Xms384m -J-Xmx512m"
* Tensorflow and opencv -- See below
* checkout homebridge.io
  * Configuring it for alexa: https://gist.github.com/johannrichard/0ad0de1feb6adb9eb61a/
* speedtest:
  * sudo apt-get install gnupg1 apt-transport-https dirmngr, lsb-release
  * export INSTALL_KEY=379CE192D401AB61
  * export DEB_DISTRO=$(lsb_release -sc)
  * sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys $INSTALL_KEY
  * echo "deb https://ookla.bintray.com/debian ${DEB_DISTRO} main" | sudo tee  /etc/apt/sources.list.d/speedtest.list
  * sudo apt-get update
  * sudo apt-get install speedtest

### Changes to libraries:
* In cli, modify get to passthrough config. Add support for dps option
* In tuyaApi, add support for dps option
* In python3: site-packages/foscam/__init__.py (from foscam.foscam import ... )

### Tensorflow/Opencv:
* Two options here: Either install TF for Py3.6 [recommended] or Opencv for Py3.5 (Opencv is officially available for py3.6)
* We tired v. hard to compile tf, but failed, so finalled compiled opencv
* For TF: [Note: building bazel will take ~1 day, building TF will take ~2 days!!]
* Confirm that odroid has sufficent power (may fail if powered froma CPU usb port).
  * If still hitting odroid reboots: cpulimit -l 10 -- <command>
* Increase system swap to 4GB:
  * grep SwapTotal /proc/meminfo
  * sudo swapoff -a
  * sudo dd if=/dev/zero of=/swapfile bs=1G count=4
  * sudo chmod 600 /swapfile
  * sudo mkswap /swapfile
  * sudo swapon /swapfile
  * Also add to fstab
* Finally did not use virtual env, but if required:
  * sudo apt-get install virtualenv
  * virtualenv --system-site-packages -p python3.6 ./python-tf/
* Build TF: https://www.tensorflow.org/install/source
  * bazel build --config=opt //tensorflow/tools/pip_package:build_pip_package --cxxopt="-D_GLIBCXX_USE_CXX11_ABI=0"
  * ./bazel-bin/tensorflow/tools/pip_package/build_pip_package /tmp/tensorflow_pkg
  * pip3 install --upgrade tensorflow-\*aarch64.whl
* Alternative (we found a TF wheel for p3.5 and compiled openCV):
  * wget https://github.com/lhelontra/tensorflow-on-arm/releases/download/v1.12.0/tensorflow-1.12.0-cp35-none-linux_aarch64.whl
  * python3.5 -m pip install --upgrade tensorflow-1.12.0-cp35-none-linux_aarch64.whl
  * python3.5 -m pip install scipy pandas keras
* opencv -- Install notes here: https://medium.com/@JMoonTech/install-opencv-and-tensorflow-on-odroid-c2-e23f13484bc0
  * cd <dir>; git clone https://github.com/Itseez/opencv.git; cd opencv; git checkout 4.0.1
  * cd <dir>; git clone https://github.com/Itseez/opencv_contrib.git; cd opencv_contrib; git checkout 4.0.1
  * cd /usr/include/aarch64-linux-gnu/ffmpeg; ln -sf /usr/include/aarch64-linux-gnu/libavformat/<avformat|avio>.h .
  * In opencv/cmake/OpenCVDetectCXXCompiler.cmake change "dumpversion" to "dumpfullversion"
  * ```
     mkdir build; cd build; cmake -DCMAKE_BUILD_TYPE=RELEASE
    -DCMAKE_INSTALL_PREFIX=/usr/local -DINSTALL_PYTHON_EXAMPLES=ON
    -DINSTALL_C_EXAMPLES=OFF
    -DOPENCV_EXTRA_MODULES_PATH=../../opencv_contrib-<ver>/modules
    -DPYTHON3_EXECUTABLE=/usr/bin/python3.5
    -DPYTHON3_LIBRARY=/usr/lib/aarch64-linux-gnu/libpython3.5m.so
    -DBUILD_EXAMPLES=OFF -DWITH_LIBV4L=OFF -DWITH_V4L=OFF
    -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_OPENCV_PYTHON3=1 i
    -DENABLE_PRECOMPILED_HEADERS=OFF
    -Wno-dev ..
    ```
  * make -j2; ...
