"""Are the header money columns exact functions of the detail lines? Decimal arithmetic on the
shortest repr of each stored double. Usage: python3 -I q2_money.py DB"""
import sqlite3
import sys
from collections import Counter, defaultdict
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal as D

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
Q4 = D("0.0001")


def dec(x):
    return D(repr(x))


def on_grid(x, places=4):
    """The stored double is the nearest double to a decimal with <= places decimals."""
    return round(x * 10**places) / 10**places == x and dec(x).as_tuple().exponent >= -places


print("## money columns on the 1e-4 grid (and on the 1e-2 cent grid)")
for t, c in [("salesorderheader", "subtotal"), ("salesorderheader", "taxamt"),
             ("salesorderheader", "freight"), ("salesorderheader", "totaldue"),
             ("salesorderdetail", "unitprice"), ("salesorderdetail", "unitpricediscount"),
             ("product", "listprice"), ("product", "standardcost"),
             ("salesperson", "salesytd"), ("salesperson", "saleslastyear"),
             ("salesperson", "commissionpct"),
             ("salesterritory", "salesytd"), ("salesterritory", "saleslastyear"),
             ("SalesPersonQuotaHistory", "SalesQuota"),
             ("currencyrate", "averagerate"), ("currencyrate", "endofdayrate")]:
    vals = [r[0] for r in con.execute(f'select "{c}" from "{t}"')]
    g4 = sum(on_grid(v, 4) for v in vals)
    g2 = sum(on_grid(v, 2) for v in vals)
    mx = max(-dec(v).as_tuple().exponent for v in vals)
    print(f"  {t}.{c}: n={len(vals)} on_1e-4={g4} on_1e-2={g2} max_decimals={mx}")

lines = defaultdict(list)
for oid, qty, up, disc in con.execute(
        "select salesorderid, orderqty, unitprice, unitpricediscount from salesorderdetail"):
    lines[oid].append((qty, dec(up), dec(disc)))
hdr = con.execute("select salesorderid, subtotal, taxamt, freight, totaldue, onlineorderflag, "
                  "territoryid from salesorderheader").fetchall()

print("\n## subtotal vs the lines")
exact = rnd4 = rnd4_line = 0
diffs = Counter()
for oid, st, tax, fr, td, onl, terr in hdr:
    lt = [up * (1 - d) * q for q, up, d in lines[oid]]
    s = sum(lt)
    exact += s == dec(st)
    rnd4 += s.quantize(Q4, ROUND_HALF_EVEN) == dec(st)
    rnd4_line += sum(x.quantize(Q4, ROUND_HALF_EVEN) for x in lt) == dec(st)
    diffs[str((dec(st) - s).quantize(D("0.000001")))] += 1
rnd4_up = sum(sum(up * (1 - d) * q for q, up, d in lines[o]).quantize(Q4, ROUND_HALF_UP) == dec(st)
              for o, st, *_ in hdr)
print(f"  orders={len(hdr)} subtotal == sum(up*(1-disc)*qty) exactly: {exact}")
print(f"  subtotal == round4_half_up(sum line totals): {rnd4_up}")
print(f"  subtotal == round4(sum line totals): {rnd4}; == sum(round4(line totals)): {rnd4_line}")
print(f"  top differences subtotal - sum(lines): {diffs.most_common(8)}")
print(f"  orders whose line totals need >4 decimals: "
      f"{sum(any((up*(1-d)*q).as_tuple().exponent < -4 for q, up, d in lines[o]) for o, *_ in hdr)}")

print("\n## taxamt and freight as rates of subtotal")
for name, idx, rate in (("taxamt", 2, D("0.08")), ("freight", 3, D("0.025"))):
    for mode in (ROUND_HALF_EVEN, ROUND_HALF_UP):
        ok = sum((dec(r[1]) * rate).quantize(Q4, mode) == dec(r[idx]) for r in hdr)
        print(f"  {name} == round4(subtotal*{rate}, {mode}): {ok}/{len(hdr)}")
    ratio = Counter(str((dec(r[idx]) / dec(r[1])).quantize(D("0.0001"))) for r in hdr)
    print(f"  {name}/subtotal ratios (4 dp): {ratio.most_common(6)}")
    bad = [(r[0], r[1], r[idx]) for r in hdr
           if (dec(r[1]) * rate).quantize(Q4, ROUND_HALF_UP) != dec(r[idx])][:5]
    print(f"  first mismatches: {bad}")

print("\n## totaldue")
dsum = sum(dec(td) == dec(st) + dec(tx) + dec(fr) for _, st, tx, fr, td, *_ in hdr)
fsum = sum(td == st + tx + fr for _, st, tx, fr, td, *_ in hdr)
print(f"  totaldue == subtotal+taxamt+freight in decimal: {dsum}/{len(hdr)}; "
      f"as float addition: {fsum}/{len(hdr)}")
fdiff = [(o, st, tx, fr, td, st + tx + fr) for o, st, tx, fr, td, *_ in hdr if td != st + tx + fr][:3]
print(f"  float-sum mismatch examples: {fdiff}")

print("\n## unitprice vs product listprice and discount")
lp = dict(con.execute("select productid, listprice from product"))
rows = con.execute("select productid, unitprice, unitpricediscount, orderqty, specialofferid "
                   "from salesorderdetail").fetchall()
ratio = Counter(str((dec(up) / dec(lp[p])).quantize(D("0.0001"))) for p, up, *_ in rows)
print(f"  unitprice/listprice (4 dp): {ratio.most_common(10)}  distinct={len(ratio)}")
print(f"  discount by specialofferid: "
      f"{sorted(Counter((s, d) for p, up, d, q, s in rows).items())}")
