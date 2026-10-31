"""Simulate the proposed rebuild rules in integer arithmetic (as views.sql would in DuckDB) and
count exact matches against the source. Usage: python3 -I q13_rebuild_rules.py DB"""
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchall()
to4 = lambda x: round(x * 10_000)        # amount in 1e-4 units (exact: all values on the grid)
to2 = lambda x: round(x * 100)
fmt = "%Y-%m-%d %H:%M:%S"
shift = lambda s, d: (datetime.strptime(s, fmt) + timedelta(days=d)).strftime(fmt)
res = []

det = q("select salesorderid, orderqty, unitprice, unitpricediscount, modifieddate from salesorderdetail")
assert all(to4(up) / 10_000 == up and to2(d) / 100 == d for _, _, up, d, _ in det)
acc = defaultdict(int)
for oid, qty, up, d, _ in det:
    acc[oid] += to4(up) * qty * (100 - to2(d))          # line total in 1e-6 units, exact
hdr = q("select salesorderid, orderdate, duedate, shipdate, status, subtotal, taxamt, freight, totaldue, "
        "comment, modifieddate from salesorderheader")
sub4 = {oid: (acc[oid] + 50) // 100 for oid in acc}     # round half up to 1e-4 (all sums >= 0)
res.append(("subtotal = (sum(up4*qty*(100-disc100)) + 50) div 100, / 1e4",
            sum(sub4[h[0]] / 10_000 == h[5] for h in hdr), len(hdr)))
res.append(("totaldue = (subtotal4 + taxamt4 + freight4) / 1e4",
            sum((sub4[h[0]] + to4(h[6]) + to4(h[7])) / 10_000 == h[8] for h in hdr), len(hdr)))
res.append(("online taxamt = round_half_up(subtotal4 * 8 / 100)",
            sum((sub4[h[0]] * 8 + 50) // 100 == to4(h[6]) for h, f in
                zip(hdr, [r[0] for r in q("select onlineorderflag from salesorderheader")]) if f == "t"),
            q("select count(*) from salesorderheader where onlineorderflag='t'")[0][0]))
res.append(("online freight = round_half_up(taxamt4 * 5 / 16)",
            sum((to4(h[6]) * 5 + 8) // 16 == to4(h[7]) for h, f in
                zip(hdr, [r[0] for r in q("select onlineorderflag from salesorderheader")]) if f == "t"),
            q("select count(*) from salesorderheader where onlineorderflag='t'")[0][0]))
res.append(("duedate = shipdate + 5 d", sum(shift(h[3], 5) == h[2] for h in hdr), len(hdr)))
res.append(("header.modifieddate = shipdate", sum(h[10] == h[3] for h in hdr), len(hdr)))
res.append(("status = '5' (text)", sum(h[4] == "5" for h in hdr), len(hdr)))
res.append(("comment = ''", sum(h[9] == "" for h in hdr), len(hdr)))
od = {h[0]: h[1] for h in hdr}
res.append(("detail.modifieddate = header.orderdate", sum(r[4] == od[r[0]] for r in det), len(det)))
ids = [h[0] for h in sorted(hdr, key=lambda h: (h[1], h[0]))]
res.append(("salesorderid = 43658 + rank(orderdate, id)", sum(i == 43659 + k for k, i in enumerate(ids)), len(ids)))
qh = q("select QuotaDate, ModifiedDate from SalesPersonQuotaHistory")
res.append(("quota ModifiedDate = QuotaDate - 45 d", sum(shift(a, -45) == b for a, b in qh), len(qh)))
cr = q("select currencyratedate, modifieddate, tocurrencycode from currencyrate")
res.append(("rate modifieddate = currencyratedate, except USD = '2014-01-02 17:39:45.26'",
            sum(m == (c if t != "USD" else "2014-01-02 17:39:45.26") for c, m, t in cr), len(cr)))
pr = q("select reviewdate, modifieddate, modifeddate from productreview")
res.append(("review modifieddate = reviewdate, modifeddate NULL",
            sum(a == b and c is None for a, b, c in pr), len(pr)))
for name, ok, n in res:
    print(f"{ok:7d}/{n:<7d} {name}")
