"""Clique Bait click log profiling. Read-only."""
import sqlite3, sys, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, date

DB = sys.argv[1]
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda s, *a: con.execute(s, a).fetchall()
def pct(xs, ps=(0, .1, .25, .5, .75, .9, .99, 1)):
    xs = sorted(xs); n = len(xs)
    return {p: xs[min(n - 1, int(p * (n - 1) + .5))] for p in ps}

print("== types")
for t in ("shopping_cart_users", "shopping_cart_events", "shopping_cart_page_hierarchy", "shopping_cart_campaign_identifier"):
    for c in [r[1] for r in q(f"pragma table_info({t})")]:
        print(t, c, q(f"select typeof({c}), count(*) from {t} group by 1"))
print("== users")
print(q("select count(*), count(distinct user_id), count(distinct cookie_id), min(start_date), max(start_date) from shopping_cart_users"))
print("cookies per user", q("select n, count(*) from (select user_id, count(*) n from shopping_cart_users group by 1) group by 1"))
print("users per cookie>1", q("select count(*) from (select cookie_id from shopping_cart_users group by 1 having count(distinct user_id)>1)"))
print("user_id range", q("select min(user_id), max(user_id) from shopping_cart_users"))
print("start_date length", q("select length(start_date), count(*) from shopping_cart_users group by 1"))
print("cookie length", q("select length(cookie_id), count(*) from shopping_cart_users group by 1"))
print("start_date by month", q("select substr(start_date,1,7), count(*) from shopping_cart_users group by 1"))
print("== events")
print(q("select count(*), count(distinct visit_id), count(distinct cookie_id), min(event_time), max(event_time) from shopping_cart_events"))
print("event cookies not in users", q("select count(distinct cookie_id) from shopping_cart_events where cookie_id not in (select cookie_id from shopping_cart_users)"))
print("user cookies without events", q("select count(*) from shopping_cart_users where cookie_id not in (select cookie_id from shopping_cart_events)"))
print("page_id coverage", q("select count(*) from shopping_cart_events where page_id not in (select page_id from shopping_cart_page_hierarchy)"))
print("event_type coverage", q("select count(*) from shopping_cart_events where event_type not in (select event_type from shopping_cart_event_identifier)"))
print("event_type mix", q("select event_type, count(*) from shopping_cart_events group by 1"))
print("type x page", q("select event_type, page_id, count(*) from shopping_cart_events group by 1,2"))
print("cookies per visit>1", q("select count(*) from (select visit_id from shopping_cart_events group by 1 having count(distinct cookie_id)>1)"))
print("dup (visit,seq)", q("select count(*) from (select visit_id, sequence_number from shopping_cart_events group by 1,2 having count(*)>1)"))
print("dup full rows", q("select count(*) from (select count(*) c from shopping_cart_events group by visit_id,cookie_id,page_id,event_type,sequence_number,event_time having c>1)"))
print("event_time fmt lengths", q("select length(event_time), count(*) from shopping_cart_events group by 1"))
print("event before user start_date", q("select count(*) from shopping_cart_events e join shopping_cart_users u using(cookie_id) where substr(e.event_time,1,10) < u.start_date"))
print("first visit date == user start_date (per cookie)", q("""select sum(f=u.start_date), count(*) from (select cookie_id, substr(min(event_time),1,10) f from shopping_cart_events group by 1) x join shopping_cart_users u using(cookie_id)"""))

ev = q("select rowid, visit_id, cookie_id, page_id, event_type, sequence_number, event_time from shopping_cart_events")
visits = defaultdict(list)
for r in ev: visits[r[1]].append(r)
seq_gap = 0; seq_not1 = 0; time_desc = 0; time_tie = 0; lens = []; durs = []
trans = Counter(); first_page = Counter(); last = Counter()
purchase_v = 0; checkout_v = 0; cart_v = 0; imp_v = 0; click_v = 0
pur_not_last = 0; pur_page = Counter(); click_wo_imp = 0; cart_before_view = 0
cart_items = []; dur_parse = lambda s: datetime.fromisoformat(s)
order_breaks = Counter()
for v, rs in visits.items():
    rs.sort(key=lambda r: r[5])
    seqs = [r[5] for r in rs]
    if seqs != list(range(1, len(rs) + 1)): seq_gap += 1
    if seqs[0] != 1: seq_not1 += 1
    ts = [r[6] for r in rs]
    time_desc += sum(1 for a, b in zip(ts, ts[1:]) if dur_parse(b) < dur_parse(a))
    time_tie += sum(1 for a, b in zip(ts, ts[1:]) if b == a)
    lens.append(len(rs))
    durs.append((dur_parse(ts[-1]) - dur_parse(ts[0])).total_seconds())
    types = [r[4] for r in rs]; pages = [r[3] for r in rs]
    first_page[(pages[0], types[0])] += 1
    last[(pages[-1], types[-1])] += 1
    pv = [(r[3]) for r in rs if r[4] == 1]
    for a, b in zip(["START"] + pv, pv + ["END"]): trans[(a, b)] += 1
    if 3 in types: purchase_v += 1
    if 12 in pv: checkout_v += 1
    if 2 in types: cart_v += 1; cart_items.append(types.count(2))
    if 4 in types: imp_v += 1
    if 5 in types: click_v += 1
    if 5 in types and 4 not in types: click_wo_imp += 1
    if 3 in types and types[-1] != 3: pur_not_last += 1
    for r in rs:
        if r[4] == 3: pur_page[r[3]] += 1
    seen = set()
    for r in rs:
        if r[4] == 1: seen.add(r[3])
        if r[4] == 2 and r[3] not in seen: cart_before_view += 1
print("visits", len(visits), "seq gaps", seq_gap, "seq not starting at 1", seq_not1)
print("time descents within visit (by seq)", time_desc, "exact ties", time_tie)
print("events per visit pct", pct(lens), "mean", round(st.mean(lens), 2))
print("visit duration s pct", pct(durs), "mean", round(st.mean(durs), 1))
print("first (page,type)", first_page.most_common(5))
print("last (page,type)", last.most_common(8))
print("visits with purchase", purchase_v, round(purchase_v / len(visits), 4), "with checkout view", checkout_v, "with cart add", cart_v, "with impression", imp_v, "with click", click_v)
print("click w/o impression", click_wo_imp, "purchase not last", pur_not_last, "purchase pages", pur_page)
print("cart add before viewing that page", cart_before_view)
print("cart items per carting visit pct", pct(cart_items))
pages = ["START"] + list(range(1, 14)) + ["END"]
print("page-view transition matrix (rows=from, counts):")
print("from\\to", pages[1:])
for a in pages[:-1]:
    row = [trans.get((a, b), 0) for b in pages[1:]]
    if sum(row): print(a, row, "n=", sum(row))

# gaps between consecutive events by (type_from,type_to)
gaps = defaultdict(list)
for v, rs in visits.items():
    for a, b in zip(rs, rs[1:]):
        gaps[(a[4], b[4])].append((dur_parse(b[6]) - dur_parse(a[6])).total_seconds())
for k in sorted(gaps):
    g = gaps[k]
    print("gap", k, "n", len(g), "p10/50/90", [round(x, 2) for x in (pct(g)[.1], pct(g)[.5], pct(g)[.9])])

# visits per cookie, cookies per user, visit time distribution
print("visits per cookie pct", pct([r[0] for r in q("select count(distinct visit_id) from shopping_cart_events group by cookie_id")]))
print("visits per user pct", pct([r[0] for r in q("select count(distinct e.visit_id) from shopping_cart_events e join shopping_cart_users u using(cookie_id) group by u.user_id")]))
print("visits by month", q("select substr(t,1,7), count(*), sum(p) from (select visit_id, min(event_time) t, max(event_type=3) p from shopping_cart_events group by 1) group by 1"))
print("visit start hour", q("select substr(t,12,2), count(*) from (select min(event_time) t from shopping_cart_events group by visit_id) group by 1"))
# visit date vs user start_date gap
print("visit start - cookie first visit (days) pct", pct([r[0] for r in q("""select julianday(substr(v.t,1,10)) - julianday(f.f) from
  (select visit_id, cookie_id, min(event_time) t from shopping_cart_events group by 1,2) v join
  (select cookie_id, substr(min(event_time),1,10) f from shopping_cart_events group by 1) f using(cookie_id)""")]))

# campaigns
camp = q("select campaign_id, products, start_date, end_date from shopping_cart_campaign_identifier")
vs = q("""select visit_id, min(event_time) t, max(event_type=3) p, max(event_type=4) imp, max(event_type=5) clk, sum(event_type=2) carts
 from shopping_cart_events group by 1""")
inwin = Counter(); stats = defaultdict(lambda: [0, 0, 0, 0, 0])
for v, t, p, imp, clk, carts in vs:
    d = t[:10]; c = [cid for cid, _, s, e in camp if s <= d <= e]
    key = c[0] if c else None
    inwin[len(c)] += 1
    s = stats[key]; s[0] += 1; s[1] += p; s[2] += imp; s[3] += clk; s[4] += carts
print("visits by #campaign windows covering start date", inwin)
for k, s in stats.items():
    print("campaign", k, "visits", s[0], "purchase rate", round(s[1] / s[0], 4), "imp rate", round(s[2] / s[0], 4), "click rate", round(s[3] / s[0], 4), "carts/visit", round(s[4] / s[0], 3))
print("impression visits outside any window", sum(1 for v, t, p, imp, clk, carts in vs if imp and not any(s <= t[:10] <= e for _, _, s, e in camp)))
print("conversion by impression/click", q("""select imp, clk, count(*), avg(p), avg(carts) from (select visit_id, max(event_type=4) imp, max(event_type=5) clk, max(event_type=3) p, sum(event_type=2) carts from shopping_cart_events group by 1) group by 1,2"""))
# impression position in sequence
print("impression seq position", q("select sequence_number, count(*) from shopping_cart_events where event_type=4 group by 1 order by 2 desc limit 5"))
print("impression preceded-by", q("""select b.event_type, b.page_id, count(*) from shopping_cart_events a join shopping_cart_events b on a.visit_id=b.visit_id and b.sequence_number=a.sequence_number-1 where a.event_type=4 group by 1,2 order by 3 desc limit 5"""))
print("click preceded-by", q("""select b.event_type, b.page_id, count(*) from shopping_cart_events a join shopping_cart_events b on a.visit_id=b.visit_id and b.sequence_number=a.sequence_number-1 where a.event_type=5 group by 1,2 order by 3 desc limit 5"""))
print("click followed-by", q("""select b.event_type, b.page_id, count(*) from shopping_cart_events a join shopping_cart_events b on a.visit_id=b.visit_id and b.sequence_number=a.sequence_number+1 where a.event_type=5 group by 1,2 order by 3 desc limit 5"""))
print("cart-add preceded-by same page view", q("""select b.event_type=1 and b.page_id=a.page_id, count(*) from shopping_cart_events a join shopping_cart_events b on a.visit_id=b.visit_id and b.sequence_number=a.sequence_number-1 where a.event_type=2 group by 1"""))
print("product views per visit (distinct product pages)", pct([r[0] for r in q("select count(distinct page_id) from shopping_cart_events where event_type=1 and page_id between 3 and 11 group by visit_id")]))
print("visits with zero product views", q("select count(*) from (select visit_id, sum(event_type=1 and page_id between 3 and 11) n from shopping_cart_events group by 1) where n=0"))
print("product view counts", q("select page_id, sum(event_type=1), sum(event_type=2) from shopping_cart_events where page_id between 3 and 11 group by 1"))
print("cart->purchase at visit level (cart visits)", q("select avg(p) from (select visit_id, max(event_type=3) p, sum(event_type=2) c from shopping_cart_events group by 1) where c>0"))
print("checkout view w/o purchase", q("select count(*) from (select visit_id, max(event_type=1 and page_id=12) co, max(event_type=3) p from shopping_cart_events group by 1) where co=1 and p=0"))
print("purchase w/o checkout view", q("select count(*) from (select visit_id, max(event_type=1 and page_id=12) co, max(event_type=3) p from shopping_cart_events group by 1) where co=0 and p=1"))
print("checkout w/o cart", q("select count(*) from (select visit_id, max(event_type=1 and page_id=12) co, sum(event_type=2) c from shopping_cart_events group by 1) where co=1 and c=0"))
# physical order
rows = q("select rowid, visit_id, sequence_number, event_time from shopping_cart_events order by rowid")
print("rowid order: seq descents within same visit", sum(1 for a, b in zip(rows, rows[1:]) if a[1] == b[1] and b[2] < a[2]),
      "visit switches", sum(1 for a, b in zip(rows, rows[1:]) if a[1] != b[1]), "time descents", sum(1 for a, b in zip(rows, rows[1:]) if b[3] < a[3]))
