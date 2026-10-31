"""Run SQL queries read-only against delivery_center; print results. Usage: q.py file.sql"""
import sqlite3, sys
DB = "data/spider2/delivery_center.sqlite"
src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con = sqlite3.connect(":memory:")
src.backup(con)
for ddl in ("create index ip on payments(payment_order_id)", "create index id on deliveries(delivery_order_id)",
            "create index idr on deliveries(driver_id)", "create index io on orders(payment_order_id)",
            "create index io2 on orders(delivery_order_id)"):
    con.execute(ddl)
for stmt in open(sys.argv[1]).read().split(";\n"):
    stmt = stmt.strip()
    if not stmt: continue
    label = stmt.splitlines()[0] if stmt.startswith("--") else stmt[:80]
    print("##", label)
    cur = con.execute(stmt)
    print(" | ".join(d[0] for d in cur.description))
    for r in cur.fetchall(): print(" | ".join(str(x) for x in r))
