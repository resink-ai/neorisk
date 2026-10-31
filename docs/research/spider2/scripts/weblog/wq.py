"""Run named SQL queries read-only against log.sqlite and print results.
Usage: python3 -I wq.py DB QUERYFILE [names...]   (blocks separated by lines '-- name: X')
Values are printed with repr() so that '', NULL (None), trailing spaces and '\\N' stay distinct."""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
blocks, name, buf = [], None, []
for line in open(qf, encoding="utf-8"):
    if line.startswith("-- name:"):
        if name: blocks.append((name, "".join(buf)))
        name, buf = line.split(":", 1)[1].strip(), []
    else:
        buf.append(line)
if name: blocks.append((name, "".join(buf)))
only = set(sys.argv[3:])
for name, sql in blocks:
    if only and name not in only: continue
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"### {name}  ({len(rows)} rows)")
    print(" | ".join(cols))
    for r in rows[:400]:
        print(" | ".join(repr(x) for x in r))
    print()
