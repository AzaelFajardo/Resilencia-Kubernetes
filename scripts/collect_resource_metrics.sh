#!/usr/bin/env bash
# =====================================================================
# collect_resource_metrics.sh -- Sample `docker stats` for every
# resilencia-kubernetes container on an interval and append to a CSV.
#
# Usage:
#   ./scripts/collect_resource_metrics.sh <output.csv> <interval_seconds> <iterations>
#
# Example (sample every 2s for 60s):
#   ./scripts/collect_resource_metrics.sh /tmp/resources.csv 2 30
#
# Run this in the background while a k6 script drives load, then stop it
# (or let it finish its iteration count) and compute averages from the CSV.
# =====================================================================

set -euo pipefail

OUTPUT="${1:?Usage: collect_resource_metrics.sh <output.csv> <interval_seconds> <iterations>}"
INTERVAL="${2:?Missing interval_seconds}"
ITERATIONS="${3:?Missing iterations}"

if [ ! -s "$OUTPUT" ]; then
  echo "timestamp,container,cpu_percent,mem_usage_mib,mem_percent" > "$OUTPUT"
fi

for _ in $(seq 1 "$ITERATIONS"); do
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' \
    | grep 'resilencia-kubernetes' \
    | while IFS=',' read -r name cpu mem_usage mem_pct; do
        mem_mib=$(echo "$mem_usage" | awk -F'/' '{print $1}' | sed 's/MiB//; s/GiB//' | xargs)
        cpu_num=$(echo "$cpu" | sed 's/%//')
        mem_pct_num=$(echo "$mem_pct" | sed 's/%//')
        echo "${ts},${name},${cpu_num},${mem_mib},${mem_pct_num}" >> "$OUTPUT"
      done
  sleep "$INTERVAL"
done
