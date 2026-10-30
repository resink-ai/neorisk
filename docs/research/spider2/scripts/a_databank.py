"""Data Bank (customer_regions / customer_nodes / customer_transactions) profiling. Read-only."""
import sqlite3, sys, statistics as st
from collections import Counter, defaultdict
from datetime import date

DB = sys.argv[1]
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda s, *a: con.execute(s, a).fetchall()

def pct(xs, ps=(0, .1, .25, .5, .75, .9, .99, 1)):
    xs = sorted(xs); n = len(xs)
    return {p: xs[min(n - 1, int(p * (n - 1) + .5))] for p in ps}

print("== types / nulls")
for t in ("customer_regions", "customer_nodes", "customer_transactions"):
    cols = [r[1] for r in q(f"pragma table_info({t})")]
    for c in cols:
        print(t, c, q(f"select typeof({c}), count(*) from {t} group by 1"), "nulls", q(f"select count(*) from {t} where {c} is null")[0][0])

print("== nodes")
print("rows, customers", q("select count(*), count(distinct customer_id), min(customer_id), max(customer_id) from customer_nodes"))
print("rows per customer", q("select n, count(*) from (select customer_id, count(*) n from customer_nodes group by 1) group by 1"))
print("regions per customer", q("select n, count(*) from (select customer_id, count(distinct region_id) n from customer_nodes group by 1) group by 1"))
print("customers by region", q("select region_id, count(distinct customer_id) from customer_nodes group by 1"))
print("node_id values", q("select node_id, count(*) from customer_nodes group by 1"))
print("start range", q("select min(start_date), max(start_date) from customer_nodes"))
print("end values top", q("select end_date, count(*) from customer_nodes group by 1 order by 2 desc limit 3"))
print("max real end", q("select max(end_date) from customer_nodes where end_date<'9999'"))
print("open rows per customer", q("select n, count(*) from (select customer_id, sum(end_date like '9999%') n from customer_nodes group by 1) group by 1"))
print("start>end", q("select count(*) from customer_nodes where start_date>end_date"))
print("dup (cust,start)", q("select count(*) from (select customer_id,start_date from customer_nodes group by 1,2 having count(*)>1)"))
print("dup full rows", q("select count(*) from (select * from customer_nodes group by 1,2,3,4,5 having count(*)>1)"))
print("region in regions", q("select count(*) from customer_nodes n left join customer_regions r using(region_id) where r.region_id is null"))

rows = q("select customer_id, region_id, node_id, start_date, end_date from customer_nodes order by customer_id, start_date")
by = defaultdict(list)
for r in rows: by[r[0]].append(r)
gap = Counter(); same_node = 0; trans = 0; tenure = []; open_tenure = []
first_start = []
for c, rs in by.items():
    first_start.append(rs[0][3])
    for a, b in zip(rs, rs[1:]):
        trans += 1
        d = (date.fromisoformat(b[3]) - date.fromisoformat(a[4])).days
        gap[d] += 1
        if a[2] == b[2]: same_node += 1
    for r in rs:
        if r[4].startswith("9999"): continue
        tenure.append((date.fromisoformat(r[4]) - date.fromisoformat(r[3])).days)
print("transitions", trans, "gap(next.start - prev.end) days", sorted(gap.items()))
print("same node consecutive", same_node)
print("closed tenure days pct", pct(tenure), "mean", round(st.mean(tenure), 2))
print("tenure hist", sorted(Counter(tenure).items()))
print("first start range", min(first_start), max(first_start))
print("first start by day hist (first 5)", sorted(Counter(first_start).items())[:5], len(set(first_start)))
print("last row is open:", sum(1 for rs in by.values() if rs[-1][4].startswith('9999')), "/", len(by))
# node continuity check: does end_date of each row = start of next (closed intervals)?
# number of distinct node_id per customer
print("distinct nodes per customer", sorted(Counter(len({r[2] for r in rs}) for rs in by.values()).items()))
# open row start date
print("open start range", q("select min(start_date), max(start_date) from customer_nodes where end_date like '9999%'"))

print("== transactions")
print("rows/customers/date range", q("select count(*), count(distinct customer_id), min(txn_date), max(txn_date) from customer_transactions"))
print("by type", q("select txn_type, count(*), sum(txn_amount), min(txn_amount), max(txn_amount), avg(txn_amount) from customer_transactions group by 1"))
for t in ("deposit", "purchase", "withdrawal"):
    xs = [r[0] for r in q("select txn_amount from customer_transactions where txn_type=?", t)]
    print(t, "pct", pct(xs), "stdev", round(st.pstdev(xs), 1))
print("amount<=0", q("select count(*) from customer_transactions where txn_amount<=0"))
print("dup full rows", q("select count(*), sum(c) from (select count(*) c from customer_transactions group by customer_id,txn_date,txn_type,txn_amount having c>1)"))
print("multi txns same cust-day", q("select count(*) from (select customer_id, txn_date from customer_transactions group by 1,2 having count(*)>1)"))
print("txns per cust-day hist", q("select c, count(*) from (select count(*) c from customer_transactions group by customer_id, txn_date) group by 1"))
print("txn customer not in nodes", q("select count(distinct customer_id) from customer_transactions where customer_id not in (select customer_id from customer_nodes)"))
print("node customer w/o txns", q("select count(distinct customer_id) from customer_nodes where customer_id not in (select customer_id from customer_transactions)"))
print("by month", q("select substr(txn_date,1,7) m, count(*), count(distinct customer_id) from customer_transactions group by 1"))
print("by month/type", q("select substr(txn_date,1,7) m, txn_type, count(*) from customer_transactions group by 1,2"))
print("by weekday", q("select strftime('%w',txn_date), count(*) from customer_transactions group by 1"))
print("txns per customer pct", pct([r[0] for r in q("select count(*) from customer_transactions group by customer_id")]))
print("txns per customer-month (active) pct", pct([r[0] for r in q("select count(*) from customer_transactions group by customer_id, substr(txn_date,1,7)")]))
print("active months per customer", q("select n, count(*) from (select customer_id, count(distinct substr(txn_date,1,7)) n from customer_transactions group by 1) group by 1"))
print("first txn type", q("select txn_type, count(*) from customer_transactions t where txn_date=(select min(txn_date) from customer_transactions where customer_id=t.customer_id) group by 1"))
fs = q("select customer_id, min(txn_date) from customer_transactions group by 1")
print("first txn date range", min(r[1] for r in fs), max(r[1] for r in fs))
print("first-txn-in-Jan share", sum(r[1] < '2020-02-01' for r in fs) / len(fs))
lst = q("select customer_id, max(txn_date) from customer_transactions group by 1")
print("last txn date pct", pct([r[1] for r in lst]))
# first txn vs first node start
fn = dict(q("select customer_id, min(start_date) from customer_nodes group by 1"))
d = [(date.fromisoformat(r[1]) - date.fromisoformat(fn[r[0]])).days for r in fs if r[0] in fn]
print("first txn - first node start (days) pct", pct(d))
print("same day first txn == node start", sum(x == 0 for x in d))
# txns outside any node interval (with 9999 treated as open)
print("txns outside node intervals", q("""select count(*) from customer_transactions t where not exists (
  select 1 from customer_nodes n where n.customer_id=t.customer_id and t.txn_date between n.start_date and n.end_date)"""))
print("txns covered by >1 interval (boundary days)", q("""select count(*) from customer_transactions t where (
  select count(*) from customer_nodes n where n.customer_id=t.customer_id and t.txn_date between n.start_date and n.end_date)>1"""))
# inter-arrival
ia = []
for c, in q("select distinct customer_id from customer_transactions"):
    ds = [date.fromisoformat(r[0]) for r in q("select txn_date from customer_transactions where customer_id=? order by txn_date", c)]
    ia += [(b - a).days for a, b in zip(ds, ds[1:])]
print("inter-arrival days pct", pct(ia), "mean", round(st.mean(ia), 2), "zero-gaps", ia.count(0))
# running balance (deposit +, others -) ordered by date then a tie rule
bal_neg_cust = 0; min_end = []; ends = []; neg_ever_tie = Counter()
for c, in q("select distinct customer_id from customer_transactions"):
    rs = q("select txn_date, txn_type, txn_amount from customer_transactions where customer_id=? order by txn_date", c)
    for rule in ("dep_first", "dep_last"):
        b = 0; neg = False
        key = (lambda r: (r[0], r[1] != 'deposit')) if rule == "dep_first" else (lambda r: (r[0], r[1] == 'deposit'))
        for r in sorted(rs, key=key):
            b += r[2] if r[1] == 'deposit' else -r[2]
            neg |= b < 0
        neg_ever_tie[rule] += neg
    ends.append(b)
print("customers ever negative (deposit-first / deposit-last within day)", dict(neg_ever_tie))
print("closing balance pct", pct(ends), "share<0", round(sum(e < 0 for e in ends) / len(ends), 3))
# month-end positive counts (local064 style: per-month net)
print("local064 check: customers with positive monthly net, by month", q("""select m, sum(net>0), count(*), avg(net) from (select customer_id, substr(txn_date,1,7) m,
  sum(case when txn_type='deposit' then txn_amount when txn_type='withdrawal' then -txn_amount else 0 end) net from customer_transactions group by 1,2) group by 1"""))
print("local298 check: sum of max(0, cumulative balance) as of 1st of month", q("""
with d as (select customer_id, txn_date, case when txn_type='deposit' then txn_amount else -txn_amount end v from customer_transactions),
m as (select distinct substr(txn_date,1,7)||'-01' m from customer_transactions)
select m.m, sum(max(0,coalesce((select sum(v) from d where d.customer_id=c.customer_id and d.txn_date< m.m),0)))
from m, (select distinct customer_id from customer_transactions) c group by 1 order by 1"""))
