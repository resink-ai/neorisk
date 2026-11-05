"""Do weekly_sales and cleaned_weekly_sales rebuild exactly in DuckDB (the views engine) from
(week date as a timestamp, dims with segment NULL kept, transactions, sales)?
weekly_sales.week_date  = strftime(ts, '%-d/%-m/%y')
cleaned.week_date_formatted = strftime(ts, '%Y-%-m-%-d'); cleaned.week_date = strftime(ts, '%Y-%m-%d')
week_number = weekofyear(ts) (ISO week); avg_transaction = ((200*sales + tx) // (2*tx)) / 100.0  (decimal round-half-up)
DuckDB round(sales/tx, 2) is tested too.
Usage: uv run python -I f1_duck_rules.py DB"""
import sqlite3, sys
import duckdb, pyarrow as pa

src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = src.execute("""select w.week_date, c.week_date, c.week_date_formatted, w.segment, c.segment, c.age_band, c.demographic,
  w.transactions, w.sales, c.week_number, c.month_number, c.calendar_year, c.avg_transaction
  from weekly_sales w join cleaned_weekly_sales c on c.rowid = w.rowid""").fetchall()
names = ["raw_wd", "iso_wd", "wdf", "seg", "cseg", "ab", "dm", "tx", "sales", "wn", "mn", "cy", "avg"]
t = pa.table({n: list(c) for n, c in zip(names, zip(*rows))})
d = duckdb.connect(); d.register("t", t)
print("duckdb", duckdb.__version__)
r = d.execute("""
with e as (select *, strptime(iso_wd, '%Y-%m-%d') ts from t)
select count(*) n,
  sum((strftime(ts, '%-d/%-m/%y') = raw_wd)::int) raw_week_date_ok,
  sum((strftime(ts, '%Y-%m-%d') = iso_wd)::int) iso_ok,
  sum((strftime(ts, '%Y-%-m-%-d') = wdf)::int) formatted_ok,
  sum((weekofyear(ts) = wn)::int) isoweek_ok,
  sum((month(ts) = mn and year(ts) = cy)::int) month_year_ok,
  sum((coalesce(seg, 'unknown') = cseg)::int) segment_ok,
  sum(((case substr(seg, 2, 1) when '1' then 'Young Adults' when '2' then 'Middle Aged' when '3' then 'Retirees' when '4' then 'Retirees' else 'unknown' end) = ab)::int) age_band_ok,
  sum(((case substr(seg, 1, 1) when 'C' then 'Couples' when 'F' then 'Families' else 'unknown' end) = dm)::int) demographic_ok,
  sum((((200 * sales + tx) // (2 * tx)) / 100.0 = avg)::int) avg_half_up_ok,
  sum((round(sales / tx, 2) = avg)::int) avg_duck_round_ok
from e""").fetchone()
print(dict(zip(["n", "raw_week_date_ok", "iso_ok", "formatted_ok", "isoweek_ok", "month_year_ok", "segment_ok", "age_band_ok",
                "demographic_ok", "avg_half_up_ok", "avg_duck_round_ok"], r)))
