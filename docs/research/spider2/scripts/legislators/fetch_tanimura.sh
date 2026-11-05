#!/bin/sh
# Fetch Cathy Tanimura's "SQL for Data Analysis" (O'Reilly 2021) repo files that this catalog appears to come from.
# Usage: sh fetch_tanimura.sh OUTDIR   (untrusted downloads go to their own directory)
set -e
OUT=$1; mkdir -p "$OUT"; B=https://raw.githubusercontent.com/cathytanimura/sql_book/master
for p in "Chapter%202%3A%20Preparing%20Data%20for%20Analysis/create_date_dimension.sql" \
         "Chapter%204%3A%20Cohorts/create_legislators_table.sql" \
         "Chapter%204%3A%20Cohorts/create_legislators_terms.sql" \
         "Chapter%204%3A%20Cohorts/legislators.csv" \
         "Chapter%204%3A%20Cohorts/legislators_terms.csv"; do
  f=$(basename "$p"); curl -sfL -o "$OUT/$f" "$B/$p"; echo "$f $(wc -c < "$OUT/$f") bytes $(shasum -a 256 "$OUT/$f" | cut -c1-16)"
done
gh api repos/cathytanimura/sql_book --jq '"licence: \(.license.spdx_id // "none")"'
