"""Compare a named SQL block's answer with a gold CSV as a multiset (values as text, floats rounded to 6 dp).
Usage: python3 -I gold_check.py DB SQLFILE NAME CSV"""
import csv, sqlite3, sys
from collections import Counter
db, qf, name, gold = sys.argv[1:5]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
sql, cur = None, None
blocks = open(qf, encoding="utf-8").read().split("-- name: ")
sql = next(b.split("\n", 1)[1] for b in blocks if b.split("\n", 1)[0].strip() == name)
rows = src.execute(sql).fetchall()
def norm(v):
    try: return f"{float(v):.6f}"
    except (TypeError, ValueError): return str(v)
mine = Counter(tuple(norm(v) for v in r) for r in rows)
with open(gold, newline="", encoding="utf-8") as f:
    g = list(csv.reader(f))[1:]
theirs = Counter(tuple(norm(v) for v in r) for r in g)
print(f"{name}: mine {sum(mine.values())} rows, gold {sum(theirs.values())} rows, equal as multiset: {mine == theirs}")
for k in (mine - theirs): print("  only mine:", k)
for k in (theirs - mine): print("  only gold:", k)
