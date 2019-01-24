#!/bin/bash
DIR="/mnt/IPCam_Data"
PURGE=90
DEVICES=5
KEEP=$(expr $PURGE - 10)

df | grep -q $DIR
if [[ $? -ne 0 ]]; then 
  >&2 echo "Error: Drive $DIR is not mounted" 
  exit -1
fi
cd $DIR

STEP="Deleting all IPCam data older than $PURGE days..."
echo "$STEP"
# REM forfiles -p "." -s -m *.* /D -%lookback% /C "cmd /c del /s @path" >> logs.txt 2>&1
find . -mindepth 2 -type f -ctime +$PURGE -exec rm {} \;

STEP="Confirm all devices are logging..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -ctime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
if [[ $(echo "$OUT" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo "$OUT"
  exit -1
fi

STEP="Confirm all devices have atleast $KEEP days of data..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -ctime +80 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
if [[ $(echo "$OUT" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo "$OUT"
  exit -1
fi

STEP="Confirm all data is culled after $PURGE days..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -ctime +$PURGE | cut -d "/" -f 2 | sort | uniq -c | grep "-")
if [[ $? -ne 1 ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo "$OUT"
  exit -1
fi

echo "Done"
