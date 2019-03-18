#!/bin/bash
## Note: Do not call directly, use the *.py wrapper to active email alerts. 

DIR="/mnt/IPCam_Data"
PURGE=90                  # Days to keep the files
DEVICES=5                 # Number of foscams deployed
KEEP=$(expr $PURGE - 10)  # Min days check
CUMULATIVE="\n\nBacktrace:\n"
MAX_FILES_PER_YARD_NODE=75 # Oh noes! cobwebs! 

cd $DIR; ls -al > /dev/null
df | grep -q $DIR
if [[ $? -ne 0 ]]; then 
  >&2 echo "Error: Drive $DIR is not mounted" 
  exit -1
else
  echo "Drive $DIR is mounted"
fi

## TODO: Investigate why ctime does not work. Till then we shall fall back to mtime
STEP1="Deleting all IPCam data older than $PURGE days..."
echo -n "$STEP1"
# REM forfiles -p "." -s -m *.* /D -%lookback% /C "cmd /c del /s @path" >> logs.txt 2>&1
OUT1=$(find . -mindepth 2 -type f -mtime +$PURGE -exec rm {} \;)
CUMULATIVE="$CUMULATIVE$STEP1\n$OUT1\n"
echo "Done!"

STEP2="Confirm all devices are logging..."
echo "$STEP2"
OUT2=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP2\n$OUT2\n"
if [[ $(echo "$OUT2" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP2 failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
else 
  echo "$OUT2"
fi

STEP3="Confirm all devices have atleast $KEEP days of data..."
echo "$STEP3"
OUT3=$(find . -mindepth 2 -type f -mtime +$KEEP | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP3\n$OUT3\n"
if [[ $(echo "$OUT3" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP3 failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
else 
  echo "$OUT3"
fi

STEP4="Confirm all data beyond $PURGE days is culled..."
echo "$STEP4"
OUT4=$(find . -mindepth 2 -type f -mtime +$(expr $PURGE + 1) | cut -d "/" -f 2 | sort | uniq -c | grep "-")
RETVAL=$?
CUMULATIVE="$CUMULATIVE$STEP4\n$OUT4\n"
if [[ $RETVAL -ne 1 ]]; then 
  >&2 echo "Error: $STEP4 failed" 
  >&2 echo -en "$CUMULATIVE\n"
  >&2 find . -mindepth 2 -type f -mtime +$PURGE
  exit -1
else 
  echo "Success"
fi

STEP5="Confirm no runaway logging (> $MAX_FILES_PER_YARD_NODE files/day) in the yard ..."
FAILED=0
echo "$STEP5"
#OUT5=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
OUT5=$(echo "$OUT2" | grep "yard")
for numFiles in $(echo "$OUT5" | sed "s/^\s*\(\S*\).*$/\1/"); do
  if [[ $numFiles -gt $MAX_FILES_PER_YARD_NODE ]]; then
    FAILED=1
  fi
done
if [[ $FAILED -ne 0 ]] ; then
  >&2 echo "Error: $STEP5 failed"
  >&2 echo "$OUT5"
  exit -1
else
  echo "Success"
fi

echo "Done"
