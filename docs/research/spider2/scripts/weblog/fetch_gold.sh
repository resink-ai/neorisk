#!/bin/sh
# Fetch Spider2 gold SQL (none exists for db `log`) and gold result CSVs into ./gold/.
cd "$(dirname "$0")"; mkdir -p gold
B=https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold
for id in local329 local330 local331 local358 local360; do
  printf '%s sql: %s\n' $id "$(curl -s -o /dev/null -w '%{http_code}' $B/sql/$id.sql)"
  for s in "" _a _b _c _d; do
    c=$(curl -s -o gold/$id$s.csv -w '%{http_code}' $B/exec_result/$id$s.csv)
    [ "$c" = 200 ] && echo "  $id$s.csv" || rm -f gold/$id$s.csv
  done
done
