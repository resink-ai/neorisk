#!/bin/sh
# Fetch Jaime M. Shaker's SQL_Coding_Challenge (github.com/iweld/SQL_Coding_Challenge): raw CSVs and the cleaning scripts.
# Usage: sh fetch_shaker.sh OUTDIR
set -e
OUT=$1; mkdir -p "$OUT"; B=https://raw.githubusercontent.com/iweld/SQL_Coding_Challenge/main/source_data
for p in csv_data/cities.csv csv_data/countries.csv csv_data/currencies.csv csv_data/languages.csv \
         scripts/build_tables.sql scripts/normalize_tables.sql scripts/remove_duplicates.sql scripts/cleanup_db.sql scripts/create_relationships.sql; do
  f=$(basename "$p"); curl -sfL -o "$OUT/$f" "$B/$p"; echo "$f $(wc -c < "$OUT/$f") bytes $(wc -l < "$OUT/$f") lines"
done
gh api repos/iweld/SQL_Coding_Challenge --jq '"licence: \(.license.spdx_id // "none"); created \(.created_at); pushed \(.pushed_at)"'
gh api 'repos/iweld/SQL_Coding_Challenge/commits?path=source_data/csv_data/cities.csv&per_page=5' --jq '.[] | "cities.csv commit \(.commit.author.date) \(.commit.message | split("\n")[0])"'
