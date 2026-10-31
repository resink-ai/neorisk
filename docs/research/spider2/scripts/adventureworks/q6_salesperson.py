"""Salesperson and territory YTD columns versus the order rows; quota history as an event stream.
Usage: python3 -I q6_salesperson.py DB"""
import sqlite3
import sys
from collections import Counter, defaultdict
from decimal import Decimal as D

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dec = lambda x: D(repr(x))
orders = con.execute("select salespersonid, territoryid, orderdate, subtotal, totaldue, onlineorderflag "
                     "from salesorderheader").fetchall()
sp = con.execute("select businessentityid, territoryid, salesquota, bonus, commissionpct, salesytd, "
                 "saleslastyear, modifieddate from salesperson order by 1").fetchall()


def window(pred, col=3, key=0):
    out = defaultdict(D)
    for o in orders:
        if o[key] != "" and pred(o[2]):
            out[o[key]] += dec(o[col])
    return out


wins = {
    "cal2014 (Jan-Jun) subtotal": window(lambda d: d >= "2014-01-01"),
    "FY2014 (Jul13-Jun14) subtotal": window(lambda d: d >= "2013-07-01"),
    "cal2013 subtotal": window(lambda d: "2013-01-01" <= d < "2014-01-01"),
    "FY2013 (Jul12-Jun13) subtotal": window(lambda d: "2012-07-01" <= d < "2013-07-01"),
    "cal2014 totaldue": window(lambda d: d >= "2014-01-01", col=4),
    "all-time subtotal": window(lambda d: True),
}
print("## salesperson.salesytd / saleslastyear vs order sums (ratio = column / window sum)")
print("id terr ytd lastyear | " + " | ".join(wins))
for r in sp:
    pid, ytd, ly = r[0], dec(r[5]), dec(r[6])
    cells = []
    for w in wins.values():
        s = w.get(pid, D(0))
        cells.append(f"{s:.4f} ({(ytd / s if s else 0):.3f}/{(ly / s if s else 0):.3f})")
    print(pid, r[1], ytd, ly, "|", " | ".join(cells))
for name, w in wins.items():
    ex_ytd = sum(w.get(r[0], D(0)) == dec(r[5]) for r in sp)
    ex_ly = sum(w.get(r[0], D(0)) == dec(r[6]) for r in sp)
    print(f"  exact matches with {name}: salesytd {ex_ytd}/17, saleslastyear {ex_ly}/17")

print("\n## salesterritory.salesytd vs sum(salesperson.salesytd) by territory, and vs orders")
terr = con.execute("select territoryid, name, salesytd, saleslastyear from salesterritory order by 1").fetchall()
sp_by_t = defaultdict(D)
sply_by_t = defaultdict(D)
for r in sp:
    if r[1] != "":
        sp_by_t[r[1]] += dec(r[5])
        sply_by_t[r[1]] += dec(r[6])
tw = {
    "cal2014 subtotal (all channels)": window(lambda d: d >= "2014-01-01", key=1),
    "FY2014 subtotal": window(lambda d: d >= "2013-07-01", key=1),
    "cal2013 subtotal": window(lambda d: "2013-01-01" <= d < "2014-01-01", key=1),
}
for t in terr:
    tid, ytd, ly = t[0], dec(t[2]), dec(t[3])
    cells = [f"{w.get(tid, D(0)):.4f}" for w in tw.values()]
    print(f"  {tid} {t[1]:15s} ytd={ytd} sum_sp_ytd={sp_by_t[tid]} eq={ytd == sp_by_t[tid]} "
          f"ly={ly} sum_sp_ly={sply_by_t[tid]} eq={ly == sply_by_t[tid]} | " + " | ".join(cells))

print("\n## salesperson.salesquota vs the latest quota history row")
q = defaultdict(list)
for e, qd, amt, g, md in con.execute('select BusinessEntityID, QuotaDate, SalesQuota, rowguid, '
                                      'ModifiedDate from SalesPersonQuotaHistory order by 1, 2'):
    q[e].append((qd, amt, md))
for r in sp:
    last = q[r[0]][-1]
    print(f"  {r[0]} terr={r[1]!r:4} quota={r[2]!r:8} bonus={r[3]} comm={r[4]} mod={r[7]} | "
          f"quotas={len(q[r[0]])} first={q[r[0]][0][0][:10]} last={last[0][:10]} last_amt={last[1]}")

print("\n## quota history: dates, lead of ModifiedDate before QuotaDate, amounts")
from datetime import date
dates = Counter(qd[:10] for v in q.values() for qd, _, _ in v)
print(f"  QuotaDate values: {sorted(dates.items())}")
lead = Counter((date.fromisoformat(qd[:10]) - date.fromisoformat(md[:10])).days for v in q.values()
               for qd, _, md in v)
print(f"  QuotaDate - ModifiedDate (days): {sorted(lead.items())}")
mult = Counter(int(a) % 1000 == 0 for v in q.values() for _, a, _ in v)
print(f"  SalesQuota multiple of 1000: {dict(mult)}")
per = Counter(len(v) for v in q.values())
print(f"  quotas per salesperson: {sorted(per.items())}")
# quota vs sales in the quarter that starts at QuotaDate
qs = []
qd_all = sorted(dates)
for e, v in q.items():
    for i, (qd, amt, _) in enumerate(v):
        start = qd[:10]
        nxt = qd_all[qd_all.index(start) + 1] if start != qd_all[-1] else "2014-07-01"
        s = sum(dec(o[3]) for o in orders if o[0] == e and start <= o[2][:10] < nxt)
        qs.append((e, start, amt, float(s)))
import statistics as stt
rat = [a / s for _, _, a, s in qs if s > 0]
print(f"  quota / subtotal in [QuotaDate, next QuotaDate): n={len(rat)} p10={stt.quantiles(rat, n=10)[0]:.3f} "
      f"p50={stt.median(rat):.3f} p90={stt.quantiles(rat, n=10)[-1]:.3f}; zero-sales quarters="
      f"{sum(1 for *_, s in qs if s == 0)}")
print(f"  corr(quota, quarter sales) = {stt.correlation([a for _, _, a, _ in qs], [s for *_, s in qs]):.3f}")
order_days = Counter(o[2][:10] for o in orders if o[5] == "f")
print(f"  reseller order days that are QuotaDates: "
      f"{sum(n for d, n in order_days.items() if d in dates)}/{sum(order_days.values())}")
print(f"  top reseller order days: {order_days.most_common(8)}")
