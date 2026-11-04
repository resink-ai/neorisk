"""Do the derived interest_metrics columns rebuild exactly in DuckDB (the views engine)?
ranking = RANK() OVER (PARTITION BY month_year ORDER BY index_value DESC)   (NULL month = its own group)
percentile_ranking = round(100 * (1 - ranking / N_month), 2)
_month, _year = parsed from month_year 'MM-YYYY' as DOUBLE; NULL when month_year is NULL.
Usage: uv run python -I f1_duck_rules.py DB"""
import sqlite3, sys
import duckdb

src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = src.execute("select rowid, _month, _year, month_year, interest_id, composition, index_value, ranking, percentile_ranking from interest_metrics").fetchall()
d = duckdb.connect()
d.execute("create table m(rid bigint, _month double, _year double, month_year varchar, interest_id double, composition double, index_value double, ranking bigint, percentile_ranking double)")
d.executemany("insert into m values (?,?,?,?,?,?,?,?,?)", rows)
q = """
with r as (select *, rank() over (partition by month_year order by index_value desc) rk,
                  count(*) over (partition by month_year) n from m),
s as (select *, round(100 * (1 - rk / n), 2) pct,
             cast(substr(month_year, 1, 2) as double) mo, cast(substr(month_year, 4, 4) as double) yr from r)
select count(*) n,
  sum((rk = ranking)::int) ranking_ok,
  sum((pct = percentile_ranking)::int) pct_round_ok,
  sum((abs(pct - percentile_ranking) < 1e-12)::int) pct_close,
  sum(((mo is not distinct from _month) and (yr is not distinct from _year))::int) month_year_ok
from s"""
print("duckdb", duckdb.__version__)
print(dict(zip(["n", "ranking_ok", "pct_round_ok", "pct_close_1e-12", "month_year_ok"], d.execute(q).fetchone())))
bad = d.execute("""with r as (select *, rank() over (partition by month_year order by index_value desc) rk, count(*) over (partition by month_year) n from m)
select month_year, ranking, n, percentile_ranking, round(100 * (1 - rk / n), 2) from r where round(100 * (1 - rk / n), 2) <> percentile_ranking limit 10""").fetchall()
print("pct mismatches sample:", bad)
