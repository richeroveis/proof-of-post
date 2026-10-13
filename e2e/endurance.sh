#!/bin/bash
# Endurance wrapper: the studio-dev storage outage has persisted for hours.
# Run full 15-attempt retry driver cycles with a long cooldown between cycles
# so a brief recovery window is caught without manual intervention.
cd "$(dirname "$0")"
for cycle in $(seq 1 12); do
  echo "=== cycle $cycle starting driver cycles at $(date -u) ===" >> endurance.log
  ./retry_driver.sh >> "endurance_cycle_${cycle}.log" 2>&1
  rc=$?
  echo "=== cycle $cycle rc=$rc at $(date -u) ===" >> endurance.log
  if [ $rc -eq 0 ]; then
    echo "DRIVER COMPLETED in cycle $cycle" >> endurance.log
    exit 0
  fi
  sleep 600
done
echo "ENDURANCE EXHAUSTED: no completed run after 12x15 attempts" >> endurance.log
exit 1
