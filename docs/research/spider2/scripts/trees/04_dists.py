"""Distributions of the 683,788 distinct trees and 216 distinct income zips.

Run: python3 -I docs/research/spider2/scripts/trees/04_dists.py
"""
import sqlite3
import statistics as st
from collections import Counter

con = sqlite3.connect("file:data/spider2/modern_data.sqlite?mode=ro", uri=True)
rows = con.execute(
    "SELECT tree_dbh, stump_diam, status, health, spc_common, zipcode, boroname FROM trees WHERE rowid > 6838"
).fetchall()
n = len(rows)
print("trees", n)


def q(xs, ps=(0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 0.999, 1)):
    xs = sorted(xs)
    return {p: xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))] for p in ps}


def share(c):
    return {k: round(v / sum(c.values()), 4) for k, v in c.most_common()}


print("status", share(Counter(r[2] for r in rows)))
print("health | Alive", share(Counter(r[3] for r in rows if r[2] == "Alive")))
print("borough", share(Counter(r[6] for r in rows)))
alive_dbh = [r[0] for r in rows if r[2] == "Alive"]
print("dbh (Alive) quantiles", q(alive_dbh), "mean", round(st.mean(alive_dbh), 3))
dead_dbh = [r[0] for r in rows if r[2] == "Dead"]
print("dbh (Dead) quantiles", q(dead_dbh))
stump = [r[1] for r in rows if r[2] == "Stump"]
print("stump_diam (Stump) quantiles", q(stump))
for b in sorted({r[6] for r in rows}):
    sub = [r for r in rows if r[6] == b]
    good = sum(r[3] == "Good" for r in sub)
    print(f"  {b}: n={len(sub)} Good/all={good/len(sub):.4f} Alive={sum(r[2]=='Alive' for r in sub)/len(sub):.4f}")
sp = Counter(r[4] for r in rows if r[4] is not None)
tot = sum(sp.values())
cum = 0
for i, (k, v) in enumerate(sp.most_common(), 1):
    cum += v
    if i in (1, 5, 10, 20, 50):
        print(f"species top {i} cover {cum/tot:.4f}")
print("species count", len(sp), "singletons", sum(v == 1 for v in sp.values()))
pz = Counter(r[5] for r in rows)
print("trees per zip quantiles", q(list(pz.values())), "zips", len(pz))
inc = con.execute("SELECT DISTINCT * FROM income_trees").fetchall()
med = [r[3] for r in inc if r[1] > 0]
mean = [r[5] for r in inc if r[1] > 0]
print("income zips", len(inc), "with households", len(med))
print("median income quantiles", q(med))
print("mean/median ratio quantiles", q([m / d for m, d in zip(mean, med)]))
print("MOE/estimate (median income) quantiles", q([r[4] / r[3] for r in inc if r[3] > 0]))
