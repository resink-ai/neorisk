"""Distributions to fit in stage 2. Usage: python3 -I q11_dists.py DB"""
import math
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchall()


def quant(v, ps=(0.1, 0.25, 0.5, 0.75, 0.9, 0.99)):
    v = sorted(v)
    return " ".join(f"p{int(p*100)}={v[min(len(v)-1, int(p*len(v)))]:.4g}" for p in ps)


hdr = q("select salesorderid, orderdate, customerid, onlineorderflag, subtotal, territoryid, salespersonid "
        "from salesorderheader")
lines = defaultdict(list)
for oid, qty, pid, so, up in q("select salesorderid, orderqty, productid, specialofferid, unitprice from salesorderdetail"):
    lines[oid].append((qty, pid, so, up))
ch = {r[0]: r[3] for r in hdr}

print("## online orders per month")
m = Counter((r[1][:7], r[3]) for r in hdr)
for k in sorted({k[0] for k in m}):
    print(f"  {k} online={m[(k, 't')]:5d} reseller={m[(k, 'f')]:4d}")

print("\n## online orders by weekday (Mon=0), 2013-07..2014-06")
wd = Counter(date.fromisoformat(r[1][:10]).weekday() for r in hdr if r[3] == "t" and r[1] >= "2013-07-01")
print("  ", sorted(wd.items()))

print("\n## lines per order and quantity per line, by channel")
for flag in ("t", "f"):
    n = [len(lines[r[0]]) for r in hdr if r[3] == flag]
    qty = [l[0] for r in hdr if r[3] == flag for l in lines[r[0]]]
    print(f"  online={flag}: lines/order mean={st.mean(n):.2f} {quant(n)} max={max(n)}")
    print(f"     lines/order mix: {sorted(Counter(min(x, 10) for x in n).items())}")
    print(f"     qty/line mean={st.mean(qty):.2f} {quant(qty)} share qty=1: {sum(x == 1 for x in qty)/len(qty):.3f}")

print("\n## subtotal by channel (log10 summaries)")
for flag in ("t", "f"):
    v = [r[4] for r in hdr if r[3] == flag]
    lg = [math.log10(x) for x in v]
    print(f"  online={flag}: n={len(v)} sum={sum(v):.2f} {quant(v)} log10 mean={st.mean(lg):.3f} sd={st.stdev(lg):.3f}")

print("\n## orders per customer, by channel")
for flag in ("t", "f"):
    c = Counter(r[2] for r in hdr if r[3] == flag)
    print(f"  online={flag}: customers={len(c)} orders/customer {sorted(Counter(min(v, 12) for v in c.values()).items())}")

print("\n## online repeat gaps (days between a customer's consecutive orders)")
byc = defaultdict(list)
for r in hdr:
    if r[3] == "t":
        byc[r[2]].append(date.fromisoformat(r[1][:10]))
gaps = [(b - a).days for v in byc.values() for a, b in zip(sorted(v), sorted(v)[1:])]
print(f"  n={len(gaps)} {quant(gaps)} same-day={sum(g == 0 for g in gaps)}")

print("\n## online first orders per month (new-customer arrivals)")
first = Counter(min(v).strftime("%Y-%m") for v in byc.values())
print("  ", " ".join(f"{k}:{v}" for k, v in sorted(first.items())))

print("\n## reseller cadence: months between a reseller's consecutive orders")
byr = defaultdict(list)
for r in hdr:
    if r[3] == "f":
        d = date.fromisoformat(r[1][:10])
        byr[r[2]].append(d.year * 12 + d.month)
rg = Counter(b - a for v in byr.values() for a, b in zip(sorted(v), sorted(v)[1:]))
print(f"  resellers={len(byr)} gap months: {sorted(rg.items())[:12]}")
print(f"  orders per reseller: {quant([len(v) for v in byr.values()])}")

print("\n## product mix")
pq = Counter()
for oid, ls in lines.items():
    for qty, pid, so, up in ls:
        pq[pid] += 1
tot = sum(pq.values())
top = pq.most_common()
print(f"  products sold={len(pq)} top1 share={top[0][1]/tot:.3f} top10 share={sum(v for _, v in top[:10])/tot:.3f} "
      f"top50 share={sum(v for _, v in top[:50])/tot:.3f}")
cat = dict(q("select p.productid, c.name from product p join productsubcategory s on s.productsubcategoryid=p.productsubcategoryid "
             "join productcategory c using(productcategoryid)"))
for flag in ("t", "f"):
    cm = Counter(cat[pid] for r in hdr if r[3] == flag for _, pid, _, _ in lines[r[0]])
    n = sum(cm.values())
    print(f"  line category mix online={flag}: " + ", ".join(f"{k} {v/n:.3f}" for k, v in cm.most_common()))
print(f"  special offer mix (lines): {sorted(Counter(so for ls in lines.values() for _, _, so, _ in ls).items())}")

print("\n## salesperson share of reseller orders")
sp = Counter(r[6] for r in hdr if r[3] == "f")
print("  ", sp.most_common())

print("\n## currency daily log-return sd (averagerate), per currency")
for cur, in q("select distinct tocurrencycode from currencyrate order by 1"):
    v = [r[0] for r in q(f"select averagerate from currencyrate where tocurrencycode='{cur}' order by currencyratedate")]
    lr = [math.log(b / a) for a, b in zip(v, v[1:])]
    print(f"  {cur}: n={len(v)} first={v[0]} last={v[-1]} sd={st.pstdev(lr):.5f} max|r|={max(map(abs, lr)):.4f}")

print("\n## quota amounts per quarter")
qa = [r[0] for r in q("select SalesQuota from SalesPersonQuotaHistory")]
print(f"  n={len(qa)} {quant(qa)}")
