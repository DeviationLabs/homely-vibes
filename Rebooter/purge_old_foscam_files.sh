#!/bin/bash
DIR="/mnt/IPCam_Data"
PURGE=90
DEVICES=5
KEEP=$(expr $PURGE - 10)
CUMULATIVE="\n\nBacktrace:\n"
MAX_FILES_PER_YARD_NODE=100

cd $DIR; ls -al > /dev/null
df | grep -q $DIR
if [[ $? -ne 0 ]]; then 
  >&2 echo "Error: Drive $DIR is not mounted" 
  exit -1
else
  echo "Drive $DIR is mounted"
fi

## TODO: Investigate why ctime does not work. Till then we shall fall back to mtime
STEP="Deleting all IPCam data older than $PURGE days..."
echo -n "$STEP"
# REM forfiles -p "." -s -m *.* /D -%lookback% /C "cmd /c del /s @path" >> logs.txt 2>&1
OUT=$(find . -mindepth 2 -type f -mtime +$PURGE -exec rm {} \;)
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
echo "Done!"

STEP="Confirm all devices are logging..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
if [[ $(echo "$OUT" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
else 
  echo "$OUT"
fi

STEP="Confirm all devices have atleast $KEEP days of data..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime +$KEEP | cut -d "/" -f 2 | sort | uniq -c | grep "-")
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
if [[ $(echo "$OUT" | wc -l) -ne $DEVICES ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo -en "$CUMULATIVE"
  exit -1
else 
  echo "$OUT"
fi

STEP="Confirm all data is culled after $PURGE days..."
echo "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime +$PURGE | cut -d "/" -f 2 | sort | uniq -c | grep "-")
RETVAL=$?
CUMULATIVE="$CUMULATIVE$STEP\n$OUT\n"
if [[ $RETVAL -ne 1 ]]; then 
  >&2 echo "Error: $STEP failed" 
  >&2 echo -en "$CUMULATIVE\n"
  >&2 find . -mindepth 2 -type f -mtime +$PURGE
  exit -1
else 
  echo "Success"
fi

STEP="Confirm no runaway logging in the yard ..."
FAILED=0
echo -n "$STEP"
OUT=$(find . -mindepth 2 -type f -mtime -1 | cut -d "/" -f 2 | sort | uniq -c | grep "-")
for numFiles in $(echo "$OUT" | grep "yard" | cut -d" " -f 1); do
  if [[ $numFiles -gt $MAX_FILES_PER_YARD_NODE ]]; then
    FAILED=1
  fi
done
if [[ $FAILED -ne 0 ]] ; then
  >&2 echo "Error: $STEP failed"
  >&2 echo "$OUT"
  exit -1
else
  echo "Done"
fi

echo "Done"
