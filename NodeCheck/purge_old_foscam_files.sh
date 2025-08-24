#!/bin/bash
## Note: Do not call directly, use the *.py wrapper to active email alerts. 
BASEDIR=$(dirname "$0")
source "$BASEDIR/../lib/Constants.sh"
SUCCESS=1
KEEP=$(expr $PURGE_AFTER_DAYS - 10)  # Min days check
CUMULATIVE="\n\nBacktrace:\n"

cd $FOSCAM_DIR; ls -al > /dev/null
df | grep -q $FOSCAM_DIR
if [[ $? -ne 0 ]]; then 
  >&2 echo "Error: Drive $FOSCAM_DIR is not mounted" 
  exit -1
else
  echo "Drive $FOSCAM_DIR is mounted"
fi

## TODO: Investigate why ctime does not work. Till then we shall fall back to mtime
STEP1="Deleting all IPCam data older than $PURGE_AFTER_DAYS days..."
echo -n "$STEP1"
# REM forfiles -p "." -s -m *.* /D -%lookback% /C "cmd /c del /s @path" >> logs.txt 2>&1
OUT1=$(find . -mindepth 2 -type f -mtime +$PURGE_AFTER_DAYS -exec rm {} \;)
CUMULATIVE="$CUMULATIVE$STEP1\n$OUT1\n"
echo "Done!"

STEP2="Confirm all devices are logging..."
echo "$STEP2"
OUT2=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP2\n$OUT2\n"
if [[ $(echo "$OUT2" | wc -l) -lt $MIN_ACTIVE_DEVICES ]]; then 
  >&2 echo "Error: $STEP2 failed" 
  >&2 echo -en "$CUMULATIVE"
  SUCCESS=0
else 
  echo "$OUT2"
fi

STEP3="Confirm all devices have at least $KEEP days of data..."
echo "$STEP3"
OUT3=$(find . -mindepth 2 -type f -mtime +$KEEP | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP3\n$OUT3\n"
if [[ $(echo "$OUT3" | wc -l) -lt $MIN_ACTIVE_DEVICES ]]; then 
  >&2 echo "Error: $STEP3 failed" 
  >&2 echo -en "$CUMULATIVE"
  SUCCESS=0
else 
  echo "$OUT3"
fi

STEP4="Confirm all data beyond $PURGE_AFTER_DAYS days is culled..."
echo "$STEP4"
OUT4=$(find . -mindepth 2 -type f -mtime +$(expr $PURGE_AFTER_DAYS + 1) | cut -d "/" -f 2 | sort | uniq -c | grep "-")
RETVAL=$?
CUMULATIVE="$CUMULATIVE$STEP4\n$OUT4\n"
if [[ $RETVAL -ne 1 ]]; then 
  >&2 echo "Error: $STEP4 failed" 
  >&2 echo -en "$CUMULATIVE\n"
  >&2 find . -mindepth 2 -type f -mtime +$PURGE_AFTER_DAYS
  SUCCESS=0
else 
  echo "Success"
fi

STEP5="Confirm no runaway logging (> $MAX_FILES_PER_YARD_NODE files/day) in the yard ..."
FAILED=0
echo "$STEP5"
#OUT5=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
OUT5=$(echo "$OUT2" | grep -i "yard")
for numFiles in $(echo "$OUT5" | sed "s/^\s*\(\S*\).*$/\1/"); do
  if [[ $numFiles -gt $MAX_FILES_PER_YARD_NODE ]]; then
    FAILED=1
  fi
done
if [[ $FAILED -ne 0 ]] ; then
  >&2 echo "Error: $STEP5 failed"
  >&2 echo "$OUT5"
  SUCCESS=0
else
  echo "Success"
fi

if [[ $SUCCESS -eq 0 ]]; then 
  >&2 echo "Something failed..."
  exit -1
fi

echo "Done"
