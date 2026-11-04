"""Spider2's prepended-duplicate fingerprint across the non-pizza modern_data tables.

For each table: k = length of the leading run of rows that each have an identical row
further down; base = n - k; compare k with round(1% of base). Also counts exact duplicate
rows left inside the base.

Run: python3 -I docs/research/spider2/scripts/modern_misc/05_dup_fingerprint.py
"""
import sqlite3
from collections import Counter

con = sqlite3.connect("file:data/spider2/modern_data.sqlite?mode=ro", uri=True)
tables = ["companies_funding", "companies_dates", "companies_industries", "trees", "income_trees", "statistics", "word_list",
          "pizza_customer_orders", "pizza_runner_orders", "pizza_toppings"]
for t in tables:
    rows = [r[1:] for r in con.execute(f'SELECT rowid, * FROM "{t}" ORDER BY rowid')]
    n = len(rows)
    later = Counter(rows)
    k = 0
    for r in rows:
        later[r] -= 1
        if later[r] >= 1:
            k += 1
        else:
            break
    base = rows[k:]
    inside = sum(c - 1 for c in Counter(base).values() if c > 1)
    print(f"{t:22s} n={n:7d} leading_dup_run k={k:5d} base={len(base):7d} 1%_of_base={len(base)/100:9.2f} "
          f"round={round(len(base)/100):5d} match={k == round(len(base)/100)} dup_rows_inside_base={inside}")
