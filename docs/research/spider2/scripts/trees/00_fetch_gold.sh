#!/bin/sh
# Run from the repo root: sh docs/research/spider2/scripts/trees/00_fetch_gold.sh
# Fetches gold SQL (if any) and gold CSVs (_a.._e) for: local040 local041
B=https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold
D=docs/research/spider2/scripts/trees/gold
mkdir -p $D
for id in local040 local041; do
  c=$(curl -s -o $D/$id.sql -w '%{http_code}' $B/sql/$id.sql); echo "$id sql http $c"; [ "$c" = 200 ] || rm -f $D/$id.sql
  for s in _a _b _c _d _e; do
    c=$(curl -s -o $D/$id$s.csv -w '%{http_code}' $B/exec_result/$id$s.csv)
    if [ "$c" = 200 ]; then echo "$id$s.csv present"; else rm -f $D/$id$s.csv; fi
  done
done
