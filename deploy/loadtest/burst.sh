#!/bin/bash
# Usage: burst.sh <run-label> <procs> <total> [lead]
#   procs = 1 (1 x total) ou 2 (2 x total/2)
# Lance la rafale depuis des conteneurs jetables a ulimit 65536 et rend le verdict JSON.
set -uo pipefail
RUN="$1"; PROCS="$2"; TOTAL="$3"; LEAD="${4:-12}"
URL="${SF_URL:-ws://127.0.0.1:8080/api/v1/ws/player}"
IMG=sfloadgen
rm -f /tmp/out_g*.json /tmp/err_g*.txt

T0=$(python3 -c "import time;print(time.time()+$LEAD)")
PER=$((TOTAL / PROCS))

launch() { # tag offset
  docker run --rm --network host --ulimit nofile=65536:65536 -v /tmp:/host "$IMG" \
    python /host/gen.py --tokens "/host/${SF_TOKENS:-tokens.txt}" --offset "$2" --count "$PER" \
    --url "$URL" --t0 "$T0" --tag "$1" > "/tmp/out_$1.json" 2> "/tmp/err_$1.txt"
}

if [ "$PROCS" = "1" ]; then
  launch g1 0
else
  launch g1 0 &
  launch g2 "$PER" &
  wait
fi

for f in /tmp/err_g*.txt; do [ -s "$f" ] && { echo "STDERR $f:"; head -5 "$f"; }; done
python3 /tmp/agg.py "$RUN" "${PROCS}x${PER}" /tmp/out_g*.json
