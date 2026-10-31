"""Distributions to fit (stage 2) for complex_oracle (Oracle SH).
Usage: python3 -I dists.py DB"""
import datetime as dt, sqlite3, statistics as st, sys
from collections import Counter, defaultdict

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchall()
def qs(xs, ps=(5, 25, 50, 75, 90, 99)):
    xs = sorted(xs); n = len(xs)
    return " ".join(f"p{p}={xs[min(n - 1, int(p / 100 * n))]:.6g}" for p in ps) + f" max={xs[-1]:.6g} mean={st.mean(xs):.6g} n={n}"
def pct(c):
    tot = sum(c.values()); return ", ".join(f"{k}: {v/tot*100:.2f}%" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))

S = q("select prod_id, cust_id, time_id, channel_id, promo_id, amount_sold from sales")
print("## sales per year:", dict(Counter(r[2][:4] for r in S)))
print("## revenue per year:", {y: round(v, 2) for y, v in sorted(Counter({}).items())} or
      {y: round(sum(r[5] for r in S if r[2][:4] == y), 2) for y in sorted({r[2][:4] for r in S})})
m = Counter(r[2][:7] for r in S)
print("## sales per month:", " ".join(f"{k}:{v}" for k, v in sorted(m.items())))
d = Counter(r[2] for r in S)
print("## lines per selling day:", qs(list(d.values())))
wd = Counter(dt.date.fromisoformat(r[2]).strftime("%a") for r in S)
print("## weekday mix (lines):", pct(wd))
dom = Counter(int(r[2][8:]) for r in S)
print("## day-of-month (lines), top 8:", sorted(dom.items(), key=lambda kv: -kv[1])[:8], "median day share", st.median(dom.values()) / len(S))
print("## channel mix (lines):", pct(Counter(r[3] for r in S)))
print("## promo mix (lines):", pct(Counter(r[4] for r in S)))
print("## amount_sold:", qs([r[5] for r in S]))
# per buyer
by = defaultdict(list)
for r in S: by[r[1]].append(r)
print("## lines per buyer:", qs([len(v) for v in by.values()]))
days = {c: sorted({r[2] for r in v}) for c, v in by.items()}
print("## active days per buyer:", qs([len(v) for v in days.values()]))
print("## share of buyers with 1 active day:", sum(len(v) == 1 for v in days.values()) / len(days))
gaps = [(dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days for v in days.values() for a, b in zip(v, v[1:])]
print("## gap between a buyer's active days (d):", qs(gaps))
span = [(dt.date.fromisoformat(v[-1]) - dt.date.fromisoformat(v[0])).days for v in days.values()]
print("## buyer lifespan first->last (d):", qs(span))
first = Counter(v[0][:4] for v in days.values())
print("## buyers by first purchase year:", dict(sorted(first.items())))
last = Counter(v[-1][:4] for v in days.values())
print("## buyers by last purchase year:", dict(sorted(last.items())))
lpd = Counter((r[1], r[2]) for r in S)
print("## lines per (buyer, day):", qs(list(lpd.values())))
rev = sorted((sum(r[5] for r in v) for v in by.values()), reverse=True)
tot = sum(rev)
print("## buyer revenue concentration: top1%", round(sum(rev[: len(rev) // 100]) / tot, 3), "top10%", round(sum(rev[: len(rev) // 10]) / tot, 3))
pc = Counter(r[0] for r in S)
v = sorted(pc.values(), reverse=True)
print("## lines per product:", qs(v), "top 10 products share", round(sum(v[:10]) / len(S), 3))
# buyers by country
bc = dict(q("select k.country_name, count(distinct s.cust_id) from sales s join customers c using(cust_id) join countries k using(country_id) group by 1"))
print("## buyers by country:", pct(Counter(bc)))
lc = dict(q("select k.country_name, count(*) from sales s join customers c using(cust_id) join countries k using(country_id) group by 1"))
print("## lines by country:", pct(Counter(lc)))
# costs
C = q("select prod_id, time_id, channel_id, promo_id, unit_cost, unit_price from costs")
print("## unit_price:", qs([r[5] for r in C]))
print("## margin (price-cost)/price:", qs([(r[5] - r[4]) / r[5] for r in C]))
# price variation within a product-month and vs list price
pm = defaultdict(list)
for r in C: pm[(r[0], r[1][:7])].append(r[5])
print("## distinct unit_price per (prod, month):", qs([len(set(v)) for v in pm.values()]))
cv = [st.pstdev(v) / st.mean(v) for v in pm.values() if len(v) > 1]
print("## coefficient of variation of unit_price within (prod, month):", qs(cv))
lp = dict(q("select prod_id, prod_list_price from products"))
print("## unit_price / prod_list_price (24 catalogued products):", qs([r[5] / lp[r[0]] for r in C if r[0] in lp]))
# costs rows per (prod, day): how many channel/promo combos
cd = Counter((r[0], r[1]) for r in C)
print("## costs rows per (prod, day):", dict(Counter(cd.values())))
# promotions table
P = q("select promo_category, promo_cost, promo_begin_date, promo_end_date from promotions where promo_id <> 999")
print("## promo category mix:", pct(Counter(r[0] for r in P)))
print("## promo cost:", qs([r[1] for r in P]))
print("## promo begin month:", dict(sorted(Counter(r[2][:7] for r in P).items())))
# customers
cu = q("select cust_gender, cust_year_of_birth, cust_credit_limit, cust_valid, cust_income_level from customers")
print("## credit limit mix:", pct(Counter(r[2] for r in cu)))
buyers = set(by)
cb = q("select cust_id, cust_credit_limit, cust_gender from customers")
print("## credit limit mix among buyers:", pct(Counter(r[1] for r in cb if r[0] in buyers)))
print("## gender among buyers:", pct(Counter(r[2] for r in cb if r[0] in buyers)))
