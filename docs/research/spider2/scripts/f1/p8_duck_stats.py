"""DuckDB (the build.sql engine): can it rebuild lap_time_stats bitwise, or only within 1e-9?
Usage: uv run python -I p8_duck_stats.py data/spider2/f1.sqlite   (reads lap_times via Python sqlite3, read-only)"""
import sqlite3, sys, duckdb
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
lt = src.execute("select race_id, driver_id, lap, milliseconds from lap_times").fetchall()
st = src.execute("select race_id, driver_id, avg_milliseconds, avg_seconds, stdev_milliseconds, stdev_seconds from lap_time_stats").fetchall()
d = duckdb.connect()
d.execute("create table lt(race_id int, driver_id int, lap int, ms bigint)"); d.executemany("insert into lt values (?,?,?,?)", lt)
d.execute("create table st(race_id int, driver_id int, am double, asec double, sm double, ss double)"); d.executemany("insert into st values (?,?,?,?,?,?)", st)
print("duckdb", duckdb.__version__)
exprs = {
 "avg_ms = avg(ms)": ("avg(ms)", "am"),
 "avg_s = avg(ms/1000.0)": ("avg(ms/1000.0)", "asec"),
 "avg_s = sum(ms/1000.0)/count": ("sum(ms/1000.0)/count(*)", "asec"),
 "avg_s = list_reduce in lap order /n": ("list_reduce(list(ms/1000.0 order by lap), (a,b)->a+b)/count(*)", "asec"),
 "stdev_ms = stddev_pop(ms)": ("stddev_pop(ms)", "sm"),
 "stdev_s = stddev_pop(ms/1000.0)": ("stddev_pop(ms/1000.0)", "ss"),
 "stdev_ms = sqrt((n*sum(x^2)-sum(x)^2) as integers / n^2)": ("sqrt((count(*)::hugeint*sum(ms::hugeint*ms) - sum(ms::hugeint)*sum(ms::hugeint))::double / (count(*)::double*count(*)))", "sm"),
 "stdev_s = that / 1000": ("sqrt((count(*)::hugeint*sum(ms::hugeint*ms) - sum(ms::hugeint)*sum(ms::hugeint))::double / (count(*)::double*count(*)))/1000", "ss"),
}
for name, (e, col) in exprs.items():
    r = d.execute(f"""with a as (select race_id, driver_id, {e} v from lt group by all)
      select count(*), sum((v = {col})::int), sum((abs(v - {col}) <= 1e-9 * greatest(abs(v), abs({col})))::int) from a join st using(race_id, driver_id)""").fetchone()
    print(f"{name:45s} rows {r[0]} exact {r[1]} within1e-9 {r[2]}")
# The four stats columns have no declared type (affinity BLOB), so per the dataset contract their results
# column is string = SQLite CAST(x AS TEXT) (15 significant digits). Compare at that text precision.
print("--- as SQLite CAST(x AS TEXT) text (the contract's results type for untyped columns)")
txt = {(r, dd): t for r, dd, *t in src.execute("select race_id, driver_id, cast(avg_milliseconds as text), cast(avg_seconds as text), cast(stdev_milliseconds as text), cast(stdev_seconds as text) from lap_time_stats")}
def sqlite_text(x):  # SQLite renders REAL as %!.15g
    return src.execute("select cast(? as text)", (x,)).fetchone()[0]
for name, (e, col) in exprs.items():
    idx = {"am": 0, "asec": 1, "sm": 2, "ss": 3}[col]
    rows = d.execute(f"select race_id, driver_id, {e} from lt group by all").fetchall()
    eq = sum(1 for r, dd, v in rows if sqlite_text(v) == txt[(r, dd)][idx])
    print(f"{name:45s} text-equal {eq}/{len(rows)}")
