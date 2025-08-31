#!/bin/bash
# Often we get too many samples of one kind. This will bias the classifier as well as cause it to take too long.
# Quick hack to prune files in one directory
count=0
for i in $(ls)
do 
  count=$(expr $count + 1)
  if ! (( $count % 4 )) 
  then 
    echo "keeping $i at $count"
  else 
    \rm $i
  fi
done
