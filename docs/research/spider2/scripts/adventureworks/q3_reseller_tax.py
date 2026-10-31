"""Reseller (offline) orders: what are taxamt and freight functions of? Also the 28 orders whose
subtotal is not round4(sum of line totals). Usage: python3 -I q3_reseller_tax.py DB"""
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal as D

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
Q4 = D("0.0001")
dec = lambda x: D(repr(x))
lines = defaultdict(list)
for oid, qty, up, disc, pid in con.execute(
        "select salesorderid, orderqty, unitprice, unitpricediscount, productid from salesorderdetail"):
    lines[oid].append((qty, dec(up), dec(disc), pid))
lp = {p: dec(v) for p, v in con.execute("select productid, listprice from product")}
hdr = con.execute("select salesorderid, subtotal, taxamt, freight, onlineorderflag, revisionnumber, "
                  "territoryid, orderdate from salesorderheader").fetchall()

for flag in ("t", "f"):
    h = [r for r in hdr if r[4] == flag]
    f_eq = sum((dec(r[2]) * D("0.3125")).quantize(Q4, ROUND_HALF_UP) == dec(r[3]) for r in h)
    f_eq2 = sum((dec(r[2]) / D("3.2")).quantize(Q4, ROUND_HALF_EVEN) == dec(r[3]) for r in h)
    print(f"online={flag} n={len(h)} freight==round4(taxamt*0.3125, half-up): {f_eq}; half-even: {f_eq2}")
    fr_dev = Counter(str(dec(r[3]) - (dec(r[2]) * D('0.3125')).quantize(Q4, ROUND_HALF_UP)) for r in h)
    print(f"   freight - round4(taxamt*0.3125): {fr_dev.most_common(5)}")
    ratios = [float(dec(r[2]) / dec(r[1])) for r in h]
    print(f"   taxamt/subtotal: min={min(ratios):.5f} p50={st.median(ratios):.5f} max={max(ratios):.5f}")
    tax_eq = sum((dec(r[1]) * D('0.08')).quantize(Q4, ROUND_HALF_UP) == dec(r[2]) for r in h)
    print(f"   taxamt == round4(0.08*subtotal): {tax_eq}")

# reseller hypotheses: tax = 0.08 * X for X in candidate bases
off = [r for r in hdr if r[4] == "f"]
cands = {
    "sum(up*qty) (no discount)": lambda L: sum(up * q for q, up, d, p in L),
    "sum(listprice*qty)": lambda L: sum(lp[p] * q for q, up, d, p in L),
    "sum(listprice*qty*(1-d))": lambda L: sum(lp[p] * q * (1 - d) for q, up, d, p in L),
}
for name, f in cands.items():
    ok = sum(abs(D("0.08") * f(lines[r[0]]) - dec(r[2])) < D("0.0001") for r in off)
    rat = [float(dec(r[2]) / (D("0.08") * f(lines[r[0]]))) for r in off]
    print(f"reseller taxamt == 0.08*{name}: {ok}/{len(off)}; ratio p50={st.median(rat):.4f} "
          f"min={min(rat):.4f} max={max(rat):.4f}")
by_rev = Counter((r[5], (dec(r[1]) * D('0.08')).quantize(Q4, ROUND_HALF_UP) == dec(r[2])) for r in off)
print(f"reseller (revisionnumber, tax==8%): {sorted(by_rev.items())}")
by_year = Counter((r[7][:4], (dec(r[1]) * D('0.08')).quantize(Q4, ROUND_HALF_UP) == dec(r[2])) for r in off)
print(f"reseller (year, tax==8%): {sorted(by_year.items())}")
ratio_month = defaultdict(list)
for r in off:
    ratio_month[r[7][:7]].append(float(dec(r[2]) / dec(r[1])))
print("reseller taxamt/subtotal by month (n, min, p50, max):")
for m in sorted(ratio_month):
    v = ratio_month[m]
    print(f"   {m} {len(v):4d} {min(v):.4f} {st.median(v):.4f} {max(v):.4f}")

print("\n## orders whose subtotal != round4(sum of line totals)")
bad = []
for oid, sub, *_ in hdr:
    s = sum(up * (1 - d) * q for q, up, d, p in lines[oid])
    if s.quantize(Q4, ROUND_HALF_EVEN) != dec(sub):
        bad.append((oid, dec(sub), s, dec(sub) - s, len(lines[oid])))
print(f"n={len(bad)}; abs(diff) max={max(abs(b[3]) for b in bad)}")
for b in bad[:30]:
    print("  ", b)
