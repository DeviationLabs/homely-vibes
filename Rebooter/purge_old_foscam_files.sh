#!/bin/bash
DIR="/mnt/IPCam_Data"
PURGE=90
DEVICES=5
KEEP=$(expr $PURGE - 10)
CUMULATIVE="\n\nBacktrace:\n"

df | grep -q $DIR
if [[ $? -ne 0 ]]; then 
  >&2 echo "Error: Drive $DIR is not mounted" 
  exit -1
fi
cd $DIR

## TODO: Investigate why ctime does not work. Till then we shall fall back to mtime
STEP="Deleting all IPCam data older than $PURGE days..."
echo "$STEP"
# REM forfiles -p "." -s -m *.* /D -%lookback% /C "cmd /c del /s @path" >> logs.txt 2>&1
OUT=$(find . -mindepth 2 -type f -mtime +$PURGE -exec rm {} \;)
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"

STEP="Confirm all devices are logging..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
if [[ $(echo "$OUT" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
fi

STEP="Confirm all devices have atleast $KEEP days of data..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime +$KEEP | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
if [[ $(echo "$OUT" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
fi

STEP="Confirm all data is culled after $PURGE days..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime +$PURGE | cut -d "/" -f 2 | sort | uniq -c | grep "-")
RETVAL=$?
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
if [[ $RETVAL -ne 1 ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
fi

echo "Done"
