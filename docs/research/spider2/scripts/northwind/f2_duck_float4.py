"""Can DuckDB (the views engine) rebuild Northwind's float4-style REALs from integer cents?
Checks CAST(printf('%.9g', CAST(c/100 AS FLOAT)) AS DOUBLE) against every stored value.
Usage: uv run python -I f2_duck_float4.py DB"""
import sqlite3, sys
import duckdb

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
duck = duckdb.connect()
for t, c in [("orders", "freight"), ("order_details", "unitprice"), ("order_details", "discount"), ("products", "unitprice")]:
    vals = [r[0] for r in con.execute(f"select {c} from {t}")]
    duck.execute("create or replace table v(x double, c bigint)")
    duck.executemany("insert into v values (?, ?)", [(v, round(v * 100)) for v in vals])
    a, b, d = duck.execute("select count(*), sum((x = cast(printf('%.9g', cast(c / 100.0 as float)) as double))::int),"
                           " sum((x = cast(cast(c / 100.0 as float) as double))::int) from v").fetchone()
    print(f"{t}.{c}: n={a} printf_9g_rule={b} plain_float_widening={d}")
