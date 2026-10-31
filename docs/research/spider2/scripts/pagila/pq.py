"""Run named SQL blocks read-only against a Spider2 SQLite file and print the results.

Usage: python3 -I pq.py DB QUERYFILE [names...]
Blocks are separated by lines starting with '-- name: X'. The DB is opened with mode=ro;
nothing is ever written. Output: '### name (n rows)', a header line, then up to 120 rows.
"""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
blocks, name, buf = [], None, []
for line in open(qf, encoding="utf-8"):
    if line.startswith("-- name:"):
        if name:
            blocks.append((name, "".join(buf)))
        name, buf = line.split(":", 1)[1].strip(), []
    else:
        buf.append(line)
if name:
    blocks.append((name, "".join(buf)))
only = set(sys.argv[3:])
for name, sql in blocks:
    if only and name not in only:
        continue
    t = time.time()
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"### {name}  ({len(rows)} rows, {time.time()-t:.2f}s)")
    print(" | ".join(cols))
    for r in rows[:120]:
        print(" | ".join(repr(x) if isinstance(x, (str, bytes)) and x in ("", "\\N") else str(x) for x in r))
    print()
