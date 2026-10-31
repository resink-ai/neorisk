import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
ev = con.execute("select cookie_id, visit_id from shopping_cart_events order by rowid").fetchall()
cookies = []
for c, v in ev:
    if not cookies or cookies[-1] != c: cookies.append(c)
users = [r[0] for r in con.execute("select cookie_id from shopping_cart_users order by rowid")]
print("cookie runs in events", len(cookies), "distinct", len(set(cookies)), "same order as users table:", cookies == users)
us = con.execute("select user_id from shopping_cart_users order by rowid").fetchall()
print("users table sorted by user_id:", [u[0] for u in us] == sorted(u[0] for u in us))
# within a cookie, visits in time order?
vt = con.execute("select cookie_id, visit_id, min(rowid), min(event_time) from shopping_cart_events group by 2").fetchall()
from collections import defaultdict
d = defaultdict(list)
for c, v, r, t in vt: d[c].append((r, t))
print("cookies whose visits are stored in time order:", sum(1 for x in d.values() if [t for r, t in sorted(x)] == sorted(t for r, t in x)), "/", len(d))
