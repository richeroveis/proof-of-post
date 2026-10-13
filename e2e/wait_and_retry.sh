#!/bin/bash
# Wait until studio-dev accepts a real write (signed no-op sendTransaction), then run the driver.
cd "$(dirname "$0")"
H=0xfcdf651213c1414bad107cf869477976938e0910227867034b1dfc5aaaf660b6
for i in $(seq 1 120); do
  R=$(curl -s -m 20 -X POST https://studio-dev.genlayer.com/api -H 'Content-Type: application/json' -d "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getTransactionByHash\",\"params\":[\"$H\"],\"id\":1}")
  if echo "$R" | grep -q '"hash"'; then
    echo "watch $i: read-path OK; probing write acceptance..."
    if node probe_write.mjs > /dev/null 2>&1; then echo "WATCH: writes accepted at try $i"; break; fi
    echo "watch $i: writes still refused"; sleep 60
  else
    echo "watch $i: read path still down"; sleep 60
  fi
done
node appeal_refund_e2e.mjs 2>&1 | tee appeal_refund_run.log
