#!/bin/bash
sleept=2
while true; do
  # echo -ne "\r"$(cat /sys/devices/virtual/thermal/thermal_zone0/temp | cut -c 1,2) C
  echo -e $(cat /sys/devices/virtual/thermal/thermal_zone0/temp | cut -c 1,2) C
  sleep $sleept
done
