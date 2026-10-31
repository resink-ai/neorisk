"""Run named SQL blocks read-only against complex_oracle.sqlite and print results.
Usage: python3 -I oq.py DB QUERYFILE [names...]   (blocks separated by lines '-- name: X')
The file is opened with mode=ro and copied into memory; indexes are added to the copy only."""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con = sqlite3.connect(":memory:")
src.backup(con); src.close()          # in-memory copy; the source file is never written
for ddl in ("create index i_s_k on sales(prod_id, cust_id, time_id, channel_id, promo_id)",
            "create index i_s_c on sales(cust_id)", "create index i_s_t on sales(time_id)",
            "create index i_c_k on costs(prod_id, time_id, channel_id, promo_id)"):
    con.execute(ddl)
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
    print(f"### {name}  ({len(rows)} rows, {time.time()-t:.1f}s)")
    print(" | ".join(cols))
    for r in rows[:80]:
        print(" | ".join(repr(x) if isinstance(x, float) else str(x) for x in r))
    print(flush=True)
