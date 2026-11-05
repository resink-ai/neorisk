#!/bin/sh
# Fetch the DDL / load script and README of Luke Barousse's SQL course project (the upstream of these tables).
# Usage: sh fetch_barousse.sh OUTDIR
set -e
OUT=$1; mkdir -p "$OUT"; B=https://raw.githubusercontent.com/lukebarousse/SQL_Project_Data_Job_Analysis/main
for p in sql_load/2_create_tables.sql sql_load/3_modify_tables.sql README.md project_sql/3_top_demanded_skills.sql; do
  f=$(basename "$p"); curl -sfL -o "$OUT/$f" "$B/$p"; echo "$f $(wc -c < "$OUT/$f") bytes"
done
gh api repos/lukebarousse/SQL_Project_Data_Job_Analysis --jq '"licence: \(.license.spdx_id // "none")"'
