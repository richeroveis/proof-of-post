#!/bin/bash
# Retry the driver only on INFRASTRUCTURE failures (network down/DiskFull/crash).
# A completed run (RESULT marker in log) is a legitimate outcome, success or not.
cd "$(dirname "$0")"
for i in $(seq 1 15); do
  echo "=== driver attempt $i at $(date) ==="
  node appeal_refund_e2e.mjs > "attempt_$i.log" 2>&1
  if grep -q "================ RESULT" "attempt_$i.log"; then
    echo "driver COMPLETED on attempt $i (success=$(grep -o '"success": [a-z]*' evidence-appeal-refund.json | tail -1))"
    exit 0
  fi
  echo "attempt $i: infrastructure failure; tail:"
  grep -oE 'DiskFull|recovery mode|not accepting connections|consensus timeout|Error: [^"]{0,80}' "attempt_$i.log" | tail -3
  sleep 240
done
echo "ALL 15 ATTEMPTS HIT INFRASTRUCTURE FAILURES"; exit 1
