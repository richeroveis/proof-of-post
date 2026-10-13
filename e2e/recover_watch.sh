#!/bin/bash
cd "$(dirname "$0")"
for i in $(seq 1 9); do
  echo "recover-watch try $i at $(date)"
  if node probe_write.mjs > /dev/null 2>&1 && node probe_deploy.mjs > /dev/null 2>&1; then
    echo "NETWORK HEALTHY - launching driver loop"
    ./retry_driver.sh
    exit $?
  fi
  sleep 600
done
echo "RECOVER WATCH EXHAUSTED: network still unhealthy"; exit 1
