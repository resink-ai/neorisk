"""Do the Spider questions on activity_log depend on physical row order? Rebuild activity_log in memory in three
orders and run the order-sensitive readings (natural = ORDER BY stamp only) from q4_spider.sql.
Usage: python3 -I order_check.py DB"""
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = src.execute("select rowid, * from activity_log").fetchall()
qs = {}
name = None
for line in open("q4_spider.sql", encoding="utf-8"):
    if line.startswith("-- name:"): name = line.split(":", 1)[1].strip(); qs[name] = ""
    elif name: qs[name] += line
orders = {
    "source rowid": sorted(rows, key=lambda r: r[0]),
    "seq = (event_time, src_rowid)": sorted(rows, key=lambda r: (r[1], r[0])),
    "(event_time, session, src_rowid)": sorted(rows, key=lambda r: (r[1], r[2], r[0])),
    "reverse rowid": sorted(rows, key=lambda r: -r[0]),
}
for oname, rs in orders.items():
    m = sqlite3.connect(":memory:")
    m.execute("create table activity_log(stamp varchar(255), session varchar(255), action varchar(255), option varchar(255), path varchar(255), search_type varchar(255))")
    m.executemany("insert into activity_log values (?,?,?,?,?,?)", [r[1:] for r in rs])
    print(f"## insert order: {oname}")
    for q in ("local330_natural", "local331_natural", "local360_sessions"):
        res = m.execute(qs[q]).fetchall()
        if q == "local360_sessions": res = sorted({(r[2]) for r in res}) + [len(res)]
        print(f"  {q}: {res}")
