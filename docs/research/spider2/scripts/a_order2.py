import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = con.execute("select rowid, customer_id from customer_transactions order by rowid").fetchall()
first = [c for r, c in rows[:500]]
rest = []
for r, c in rows[500:]:
    if not rest or rest[-1] != c: rest.append(c)
print("groups after 500:", len(rest), "distinct", len(set(rest)), "customers w/o later txns", 500 - len(set(rest)))
order = [c for c in first if c in set(rest)]
print("group order equals first-block order:", rest == order)
