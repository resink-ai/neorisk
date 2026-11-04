"""Run named SQL blocks read-only against a Spider2 SQLite file and print results.
Usage: python3 -I rq.py DB QUERYFILE [names...]   (blocks separated by lines '-- name: X')
The file is opened with mode=ro and copied into memory; it is never written.
Blocks named setup* run as scripts on the in-memory copy (e.g. CREATE INDEX)."""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con = sqlite3.connect(":memory:")
src.backup(con); src.close()
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
    t = time.time()
    if name.startswith("setup"):  # index the in-memory copy only
        con.executescript(sql); print(f"### {name}  (setup, {time.time()-t:.2f}s)\n"); continue
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"### {name}  ({len(rows)} rows, {time.time()-t:.2f}s)")
    print(" | ".join(cols))
    for r in rows[:100]:
        print(" | ".join(repr(x) if isinstance(x, (str, bytes)) and (x == '' or isinstance(x, bytes)) else str(x) if not isinstance(x, bytes) else f"<blob {len(x)}>" for x in r))
    print()
