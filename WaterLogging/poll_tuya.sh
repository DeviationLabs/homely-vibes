#!/bin/bash
export PATH=$PATH:/usr/local/bin:/bin:/usr/bin
export NODE_PATH='/usr/local/lib/node_modules'

script=$0
scriptname=$(basename $script)
scriptdir=$(dirname $script)
source $scriptdir/../lib/Constants.sh

ENERGY_FIELD=4
SLEEP=3
RACHIO_INTVL=120 # Rachio rate limits on 1700 API calls, so let's stay south of this. 
TUYA_BAD_READING=-2500

# Cleanup 
# >&2 echo "Recommended invocation: nohup $script >> ~/tuya_logs/tuya_logs.csv &"
myPID=$$
foundPID=$(ps aux | grep $scriptname | grep -v ${myPID} | grep -v grep | tr -s "[:space:]"| cut -d ' ' -f 2 )
if [[ -n $foundPID ]]; then 
  kill -15 $foundPID
fi
echo

re='^[+-]?[0-9]+([.][0-9]+)?$' # Valid numbers pattern
latchedEpoch=0
while (true)
do 
  currEpoch=$(date "+%s") 
  sleep $SLEEP
  line_date=$(date "+%F-%H-%M-%S,%s") 
  line_tuya=$(tuya-cli get --id $TUYA_ID --dps $ENERGY_FIELD)
  if ! [[ $line_tuya =~ $re ]] ; then
    # echo "error: Not a number" >&2
    line_tuya=$TUYA_BAD_READING
  fi
  if [[ $latchedEpoch < $((currEpoch - $RACHIO_INTVL)) ]]; then
      latchedEpoch=$currEpoch
      temp=$(${scriptdir}/poll_rachio.js)
  fi
  line_rachio=${temp:-"-3,Script Error"} # Handle the no data case
  echo "${line_date},${line_tuya},${line_rachio}"
done

