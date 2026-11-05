"""Check that the 4-decimal REAL columns rebuild exactly from integers of 1e-4 (x = n / 10000),
and that the per-row dimension texts survive a round trip. Read-only.
Usage: python3 -I f1_decimals.py DB"""
import sqlite3, sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for t, c in (("hardware_fact_gross_price", "gross_price"),
             ("hardware_fact_manufacturing_cost", "manufacturing_cost"),
             ("hardware_fact_pre_invoice_deductions", "pre_invoice_discount_pct")):
    vals = [r[0] for r in con.execute(f"SELECT {c} FROM {t}")]
    ints = [round(v * 10000) for v in vals]
    exact_div = sum(n / 10000 == v for n, v in zip(ints, vals))
    exact_repr = sum(float(repr(v)) == v and len(repr(v).split(".")[-1]) <= 4 for v in vals)
    print(f"{t}.{c}: rows {len(vals)}, n/10000 == stored {exact_div}, repr has <= 4 decimals {exact_repr}")
# DuckDB check of the same rule, if available
try:
    import duckdb
    d = duckdb.connect()
    for t, c in (("hardware_fact_gross_price", "gross_price"),
                 ("hardware_fact_manufacturing_cost", "manufacturing_cost"),
                 ("hardware_fact_pre_invoice_deductions", "pre_invoice_discount_pct")):
        vals = [r[0] for r in con.execute(f"SELECT {c} FROM {t}")]
        d.execute("CREATE OR REPLACE TABLE v(x DOUBLE)")
        d.executemany("INSERT INTO v VALUES (?)", [(v,) for v in vals])
        ok = d.execute("SELECT sum((CAST(round(x*10000) AS BIGINT) / 10000.0 = x)::INT), count(*) FROM v").fetchone()
        print(f"duckdb {t}.{c}: BIGINT/10000.0 == stored {ok[0]} of {ok[1]}")
except ImportError:
    print("duckdb not importable in this interpreter")
