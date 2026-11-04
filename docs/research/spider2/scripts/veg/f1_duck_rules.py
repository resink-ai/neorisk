"""Do the proposed integer encodings and text formats rebuild every veg value exactly in DuckDB?
qty = grams / 1000.0, selling price = jiao / 10.0, wholesale price = fen / 100.0, loss rate = basis points / 100.0;
txn_date / whsle_date = strftime(ts, '%Y-%m-%d %H:%M:%S') of a midnight timestamp; txn_time = strftime(ts, '%H:%M:%S');
day_of_week = strftime(ts, '%A'); sale/return = sign of qty; index = row_number() over (order by seq) - 1.
Usage: uv run python -I f1_duck_rules.py DB"""
import sqlite3, sys
import duckdb, pyarrow as pa

src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
def load(sql, names):
    cols = list(zip(*src.execute(sql).fetchall()))
    return pa.table({n: list(c) for n, c in zip(names, cols)})
txn = load('''select "index", txn_date, txn_time, "qty_sold(kg)", "unit_selling_px_rmb/kg", "sale/return", day_of_week from veg_txn_df''',
           ["idx", "d", "t", "q", "px", "sr", "dow"])
wh = load('''select whsle_date, "whsle_px_rmb-kg" from veg_whsle_df''', ["d", "wp"])
lo = load('''select "loss_rate_%" from veg_loss_rate_df''', ["lr"])
d = duckdb.connect()
d.register("txn", txn); d.register("wh", wh); d.register("lo", lo)
print("duckdb", duckdb.__version__)
r = d.execute("""
with e as (select *, strptime(substr(d, 1, 10) || ' ' || t, '%Y-%m-%d %H:%M:%S') ts,
                  cast(round(q * 1000) as bigint) g, cast(round(px * 10) as bigint) jiao from txn)
select count(*) n,
  sum((g / 1000.0 = q)::int) qty_ok, sum((jiao / 10.0 = px)::int) px_ok,
  sum((strftime(date_trunc('day', ts), '%Y-%m-%d %H:%M:%S') = d)::int) date_ok, sum((strftime(ts, '%H:%M:%S') = t)::int) time_ok,
  sum((strftime(ts, '%A') = dow)::int) dow_ok, sum(((case when g < 0 then 'return' else 'sale' end) = sr)::int) sr_ok
from e""").fetchall()
print("veg_txn_df", dict(zip(["n", "qty_ok", "px_ok", "date_ok", "time_ok", "dow_ok", "sr_ok"], r[0][:7])))
print("txn index from (time, ord=index):", d.execute("select count(*), sum((rn = idx)::int) from (select idx, row_number() over (order by strptime(substr(d,1,10)||' '||t, '%Y-%m-%d %H:%M:%S'), idx) - 1 rn from txn)").fetchone())
print("veg_whsle_df fen:", d.execute("select count(*), sum((cast(round(wp * 100) as bigint) / 100.0 = wp)::int), sum((strftime(strptime(d, '%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S') = d)::int) from wh").fetchone())
print("veg_loss_rate_df bp:", d.execute("select count(*), sum((cast(round(lr * 100) as bigint) / 100.0 = lr)::int) from lo").fetchone())
