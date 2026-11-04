"""Distributions of the 1074 distinct unicorns (rows 12.. of each companies_* table).

Run: python3 -I docs/research/spider2/scripts/unicorns/05_dists.py
"""
import math
import sqlite3
import statistics as st
from collections import Counter

con = sqlite3.connect("file:data/spider2/modern_data.sqlite?mode=ro", uri=True)
rows = con.execute(
    """SELECT d.company_id, d.date_joined, d.year_founded, f.valuation, f.funding, f.select_investors, i.industry
       FROM (SELECT DISTINCT * FROM companies_dates) d
       JOIN (SELECT DISTINCT * FROM companies_funding) f USING (company_id)
       JOIN (SELECT DISTINCT * FROM companies_industries) i USING (company_id)"""
).fetchall()
print("companies", len(rows))


def q(xs, ps=(0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1)):
    xs = sorted(xs)
    return {p: xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))] for p in ps}


val = [r[3] / 1e9 for r in rows]
fund = [r[4] / 1e6 for r in rows if r[4] > 0]
print("valuation $B quantiles", q(val), "mean", round(st.mean(val), 3))
# Pareto tail: MLE alpha for valuation >= 1B (xmin = 1)
alpha = len(val) / sum(math.log(v / 1.0) for v in val)
print("valuation Pareto MLE alpha (xmin=1B):", round(alpha, 3))
print("funding $M quantiles (funding>0)", q(fund), "median", st.median(fund))
lr = [math.log10(r[4] / r[3]) for r in rows if r[4] > 0]
print("log10(funding/valuation) mean", round(st.mean(lr), 3), "sd", round(st.stdev(lr), 3))

# arrivals: per month in 2021-2022, gaps in days between consecutive distinct join dates
months = Counter(r[1][:7] for r in rows if r[1][:4] in ("2021", "2022"))
print("joins per month 2021-2022:", dict(sorted(months.items())))
import datetime as dt

ds = sorted(dt.date.fromisoformat(r[1][:10]) for r in rows)
gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
print("gap days between consecutive joins (all years): zero-gap", sum(g == 0 for g in gaps), "of", len(gaps),
      "median", st.median(gaps), "max", max(gaps))
ds21 = [d for d in ds if d.year == 2021]
g21 = [(b - a).days for a, b in zip(ds21, ds21[1:])]
print("2021 gaps: mean", round(st.mean(g21), 3), "share zero", round(sum(g == 0 for g in g21) / len(g21), 3))

age = [int(r[1][:4]) - r[2] for r in rows]
print("years from founding to unicorn quantiles", q(age), "mean", round(st.mean(age), 2))
nitems = Counter(None if r[5] is None else r[5].count(",") + 1 for r in rows)
print("investor list items", dict(nitems))
inv = Counter()
for r in rows:
    if r[5]:
        for x in r[5].strip('"').split(","):
            inv[x.strip()] += 1
print("distinct investors", len(inv), "top 8", inv.most_common(8))
print("investor names that differ only by surrounding spaces after split:",
      sum(1 for r in rows if r[5] and any(x != x.strip() and not x.startswith(" ") for x in r[5].strip('"').split(","))))
ind = Counter(r[6] for r in rows)
print("industry mix", ind.most_common())
