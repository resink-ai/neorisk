"""DuckDB check: integer cents / 100.0 reproduces web_orders' four REAL money columns. Read-only.
Usage: uv run python -I f2_duck_amounts.py DB"""
import sqlite3, sys
import duckdb
rows = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).execute(
    "SELECT standard_qty, gloss_qty, poster_qty, standard_amt_usd, gloss_amt_usd, poster_amt_usd, total_amt_usd FROM web_orders").fetchall()
d = duckdb.connect(); d.execute("CREATE TABLE o(qs BIGINT, qg BIGINT, qp BIGINT, a DOUBLE, b DOUBLE, c DOUBLE, t DOUBLE)")
d.executemany("INSERT INTO o VALUES (?,?,?,?,?,?,?)", rows)
print(d.execute("""SELECT count(*) n, sum((qs*499/100.0 = a)::INT) std, sum((qg*749/100.0 = b)::INT) gl, sum((qp*812/100.0 = c)::INT) po,
  sum(((qs*499+qg*749+qp*812)/100.0 = t)::INT) total, sum((qs*4.99 = a)::INT) std_naive, sum((a+b+c = t)::INT) total_naive FROM o""").fetchone())
print("duckdb", duckdb.__version__)
