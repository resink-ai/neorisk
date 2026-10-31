"""Distributions for stage 2: rental duration, inter-arrival times within the windows, customer
and item choice, staff mix, store crossing, and the amount mix.

Usage: python3 -I p9_dists.py DB
"""
import sqlite3, statistics as st, sys
from collections import Counter
from datetime import datetime

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
P = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")


def q(xs, ps=(0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)):
    xs = sorted(xs)
    return {p: round(xs[min(len(xs) - 1, int(p * len(xs)))], 3) for p in ps}


rows = con.execute("select rental_id, rental_date, return_date, customer_id, inventory_id, staff_id from rental").fetchall()
done = [(P(a), P(b)) for _, a, b, *_ in rows if b]

# 1. rental duration in minutes, and its histogram in 6-hour bins
mins = [(b - a).total_seconds() / 60 for a, b in done]
print("duration minutes: min", min(mins), "max", max(mins), "mean", round(st.mean(mins), 1), "sd", round(st.pstdev(mins), 1))
print("duration hours quantiles:", {k: round(v / 60, 2) for k, v in q(mins).items()})
h6 = Counter(int(m // 360) for m in mins)
print("6-hour bins (bin*6h -> n):", dict(sorted(h6.items())))
# duration as (whole days, minute-of-day remainder)?
rem = Counter(int(m % 1440 // 60) for m in mins)
print("duration mod 24h, by hour:", dict(sorted(rem.items())))
days = Counter(int(m // 1440) for m in mins)
print("duration whole days:", dict(sorted(days.items())))

# 2. inter-arrival seconds within windows (2005 only, sorted by time)
ts = sorted(P(a) for _, a, *_ in rows if a < "2006-01-01")
gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:]) if (b - a).total_seconds() < 86400]
print("inter-arrival seconds (within windows):", q(gaps), "mean", round(st.mean(gaps), 1), "cv", round(st.pstdev(gaps) / st.mean(gaps), 3))
# per window rate
win = []
for t in ts:
    if not win or (t - win[-1][-1]).total_seconds() > 2 * 86400:
        win.append([t])
    else:
        win[-1].append(t)
for w in win:
    span = (w[-1] - w[0]).total_seconds() / 86400
    g = [(b - a).total_seconds() for a, b in zip(w, w[1:])]
    print(f"  window {w[0]:%Y-%m-%d}: n={len(w)} span_d={span:.3f} per_day={len(w)/span:.1f} gap_mean_s={st.mean(g):.1f} gap_cv={st.pstdev(g)/st.mean(g):.3f}")

# 3. per-customer rentals: dispersion vs Poisson
per_c = Counter(c for _, _, _, c, _, _ in rows)
v = list(per_c.values())
print("rentals per customer: mean", round(st.mean(v), 2), "var", round(st.pvariance(v), 2), "quantiles", q(v))
# 4. per-item rentals
per_i = Counter(i for *_, i, _ in rows)
v = list(per_i.values())
print("rentals per inventory item: mean", round(st.mean(v), 3), "var", round(st.pvariance(v), 3))
# 5. per-film rentals vs copies
fc = dict(con.execute("select film_id, count(*) from inventory group by 1"))
fr = dict(con.execute("select i.film_id, count(*) from rental r join inventory i using(inventory_id) group by 1"))
ratio = [fr.get(f, 0) / n for f, n in fc.items()]
print("rentals per copy, by film: quantiles", q(ratio))
per_film = list(fr.values())
print("rentals per film (films with stock):", q(per_film), "min", min(per_film), "max", max(per_film))
# 6. staff by window
print("staff share:", dict(Counter(s for *_, s in rows)))
# 7. amount mix (all payments) and late-day mix
am = Counter(r[0] for r in con.execute("select amount from payment"))
print("amount mix (top):", dict(am.most_common(12)))
# 8. customers active per window (distinct) and repeat structure
by_w = Counter()
for _, a, *_ in rows:
    by_w[a[:7]] += 1
print("rentals by month:", dict(sorted(by_w.items())))
# 9. customer's gap between consecutive rentals (hours), 2005 only
cust = {}
for _, a, _, c, _, _ in rows:
    if a < "2006-01-01":
        cust.setdefault(c, []).append(P(a))
cg = []
for c, l in cust.items():
    l.sort()
    cg += [(b - a).total_seconds() / 3600 for a, b in zip(l, l[1:])]
print("customer re-rental gap hours:", q(cg))
# 10. rental duration vs film rental_duration (correlation)
x = con.execute("""select f.rental_duration, (julianday(return_date)-julianday(rental_date)) from rental r
  join inventory i using(inventory_id) join film f using(film_id) where return_date is not null""").fetchall()
a = [r[0] for r in x]; b = [r[1] for r in x]
ma, mb = st.mean(a), st.mean(b)
cov = sum((p - ma) * (r - mb) for p, r in zip(a, b)) / len(a)
print("corr(film.rental_duration, days kept) =", round(cov / (st.pstdev(a) * st.pstdev(b)), 4))
