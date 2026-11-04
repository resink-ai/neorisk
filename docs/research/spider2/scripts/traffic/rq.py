"""Run named SQL blocks read-only against a Spider2 SQLite file and print results.
Usage: python3 -I rq.py DB QUERYFILE [names...]   (blocks separated by lines '-- name: X')
The file is opened with mode=ro and copied into memory (indexes on case_id/id are added to the copy only); it is never written."""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con = sqlite3.connect(":memory:")
src.backup(con); src.close()
for t in ("collisions","case_ids","parties","victims"):
    con.execute(f"create index ix_{t}_case on {t}(case_id)")  # in-memory copy only
con.execute("create index ix_p_cp on parties(case_id, party_number)")
con.execute("create index ix_p_id on parties(id)"); con.execute("create index ix_v_id on victims(id)")
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
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"### {name}  ({len(rows)} rows, {time.time()-t:.2f}s)")
    print(" | ".join(cols))
    for r in rows[:100]:
        print(" | ".join(repr(x) if isinstance(x, (str, bytes)) and (x == '' or isinstance(x, bytes)) else str(x) if not isinstance(x, bytes) else f"<blob {len(x)}>" for x in r))
    print()
