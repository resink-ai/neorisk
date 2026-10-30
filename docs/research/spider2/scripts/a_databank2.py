"""Data Bank part 2: row order, rates, local300 reproduction, round-trip prototype. Read-only."""
import sqlite3, sys, statistics as st
from collections import Counter, defaultdict
from datetime import date, timedelta

DB = sys.argv[1]
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda s, *a: con.execute(s, a).fetchall()

# physical row order
tx = q("select rowid, customer_id, txn_date, txn_type, txn_amount from customer_transactions order by rowid")
inv = lambda key: sum(1 for a, b in zip(tx, tx[1:]) if key(a) > key(b))
print("txn rowid contiguous", tx[0][0], tx[-1][0], len(tx))
print("txn order descents by date", inv(lambda r: r[2]), "by customer", inv(lambda r: r[1]), "by (cust,date)", inv(lambda r: (r[1], r[2])))
print("first 12 dates", [r[2] for r in tx[:12]])
nd = q("select rowid, customer_id, start_date from customer_nodes order by rowid")
print("node order descents by customer", sum(1 for a, b in zip(nd, nd[1:]) if a[1] > b[1]), "by start", sum(1 for a, b in zip(nd, nd[1:]) if a[2] > b[2]))
print("node first rows", nd[:3], nd[498:503])
# node rows are 7 blocks of 500 (one per allocation round)?
blocks = [[r[1] for r in nd[i*500:(i+1)*500]] for i in range(7)]
print("node blocks of 500 each = customers 1..500", all(b == list(range(1, 501)) for b in blocks))
nodes = q("select customer_id, region_id, node_id, start_date, end_date from customer_nodes order by rowid")
print("block k start_date monotone within customer", all(
    nodes[k*500 + c][3] < nodes[(k+1)*500 + c][3] for k in range(6) for c in range(500)))

# per-month activity rates
spans = q("select customer_id, min(txn_date), max(txn_date), count(*) from customer_transactions group by 1")
rates = []
for c, a, b, n in spans:
    days = (date.fromisoformat(b) - date.fromisoformat(a)).days + 1
    rates.append(n / days * 30)
r = sorted(rates)
print("txns per 30d over own active span: p10/p50/p90", round(r[50], 2), round(r[250], 2), round(r[450], 2), "mean", round(st.mean(r), 2))
# rate from first txn to global end
gl = date(2020, 4, 28)
r2 = sorted(n / ((gl - date.fromisoformat(a)).days + 1) * 30 for c, a, b, n in spans)
print("txns per 30d first->2020-04-28: p10/p50/p90", round(r2[50], 2), round(r2[250], 2), round(r2[450], 2), "mean", round(st.mean(r2), 2))
# per-customer counts per month incl zero (Feb, Mar full months)
for m in ("2020-02", "2020-03"):
    cnt = dict(q("select customer_id, count(*) from customer_transactions where substr(txn_date,1,7)=? group by 1", m))
    xs = [cnt.get(c, 0) for c in range(1, 501)]
    mu = st.mean(xs); var = st.pvariance(xs)
    print(m, "per-customer count mean", round(mu, 2), "var", round(var, 2), "zero share", round(xs.count(0) / 500, 3), "hist", sorted(Counter(xs).items()))
# type mix excluding each customer's first txn
rest = q("""select txn_type, count(*) from customer_transactions t where rowid not in (
  select (select rowid from customer_transactions t2 where t2.customer_id=t.customer_id order by txn_date, rowid limit 1) from (select distinct customer_id from customer_transactions) t) group by 1""")
print("type mix excluding first txn", rest)
# customer-level heterogeneity: deposit share per customer
ds = [r[0] for r in q("select avg(txn_type='deposit') from customer_transactions group by customer_id")]
print("per-customer deposit share mean/sd", round(st.mean(ds), 3), round(st.pstdev(ds), 3))
# Is amount independent of type and customer? per-customer mean amount spread vs expectation
am = [r[0] for r in q("select avg(txn_amount) from customer_transactions group by customer_id having count(*)>=10")]
print("per-customer mean amount (n>=10) sd", round(st.pstdev(am), 1), "n", len(am))
print("amount==1000 count", q("select txn_type, count(*) from customer_transactions where txn_amount in (0,1000) group by 1"))

# local300 reproduction: daily balance carried forward, negatives -> 0, monthly max per customer, sum
by = defaultdict(lambda: defaultdict(int))
for _, c, d, t, a in tx:
    by[c][d] += a if t == 'deposit' else -a
tot = Counter()
for c, dd in by.items():
    d0 = date.fromisoformat(min(dd)); d1 = date.fromisoformat(max(dd)); b = 0; mx = {}
    d = d0
    while d <= d1:
        b += dd.get(d.isoformat(), 0)
        m = d.isoformat()[:7]
        mx[m] = max(mx.get(m, 0), max(b, 0))
        d += timedelta(days=1)
    for m, v in mx.items(): tot[m] += v
print("local300 reproduction", sorted(tot.items()))

# Round-trip prototype: derive events, rebuild tables, compare multisets
events = []
for i, (cid, reg, node, s, e) in enumerate(nodes):
    kind = "account_opened" if i < 500 else "node_reassigned"
    events.append((s, 0, cid, kind, {"region_id": reg, "node_id": node}))
for rid, c, d, t, a in tx:
    events.append((d, 1, c, "txn_" + t, {"amount": a, "src_rowid": rid}))
events.sort(key=lambda e: (e[0], e[1], e[2]))
cur = {}; rebuilt_nodes = []; rebuilt_tx = []
for d, _, c, k, p in events:
    if k in ("account_opened", "node_reassigned"):
        if c in cur:
            prev = cur[c]; rebuilt_nodes.append((c, prev[0], prev[1], prev[2], (date.fromisoformat(d) - timedelta(days=1)).isoformat()))
        cur[c] = (p["region_id"], p["node_id"], d)
    else:
        rebuilt_tx.append((p["src_rowid"], c, d, k[4:], p["amount"]))
for c, (r, n, s) in cur.items():
    rebuilt_nodes.append((c, r, n, s, "9999-12-31"))
print("round-trip nodes multiset equal", Counter(rebuilt_nodes) == Counter(tuple(x) for x in nodes))
print("round-trip txns equal incl rowid", sorted(rebuilt_tx) == sorted(tx))
print("events", Counter(e[3] for e in events))
