"""Timestamp format round trip, created_* redundancy, out-of-order moments, metric derivation search."""
import sys, itertools
sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
con = connect(); cols, rows = load_orders(con); ix = {c: i for i, c in enumerate(cols)}
n = len(rows)
bad = 0; rt_bad = 0
T = np.full((n, 8), np.nan)
for r, row in enumerate(rows):
    for k, m in enumerate(MOMENTS):
        s = row[ix[f"order_moment_{m}"]]
        if s is None: continue
        t = parse(s); T[r, k] = t
        if fmt(t) != s: rt_bad += 1
print("format round-trip mismatches:", rt_bad)
yrs = sorted(set(int(x) for x in (T[:,0]//86400)))
import datetime as dtm
cre = [dtm.datetime(1970,1,1)+dtm.timedelta(seconds=t) for t in T[:,0]]
print("created range", min(cre), max(cre))
mis = {k:0 for k in ["hour","minute","day","month","year"]}
for row, c in zip(rows, cre):
    for k in mis:
        if row[ix[f"order_created_{k}"]] != getattr(c, k): mis[k]+=1
print("created_* mismatches vs moment_created:", mis)
# seconds: are all moments whole seconds? text always has seconds
# out-of-order: any later moment earlier than an earlier moment (pairwise consecutive non-null)
status = np.array([row[ix["order_status"]] for row in rows])
names = MOMENTS
print("pairwise violations (later stage < earlier stage) among both non-null:")
for a, b in itertools.combinations(range(8), 2):
    both = ~np.isnan(T[:,a]) & ~np.isnan(T[:,b])
    v = (T[:,b] < T[:,a]) & both
    if v.sum(): print(f"  {names[a]} > {names[b]}: {v.sum()} of {both.sum()} ({100*v.sum()/both.sum():.2f}%)")
anyv = np.zeros(n, bool)
for a in range(8):
    for b in range(a+1, 8):
        anyv |= (T[:,b] < T[:,a])
print("orders with any out-of-order pair:", anyv.sum(), f"{100*anyv.mean():.2f}%")
# metric derivation: for each metric, test every ordered pair diff/60 match
M = np.array([[np.nan if row[ix[f"order_metric_{m}"]] is None else row[ix[f"order_metric_{m}"]] for m in METRICS] for row in rows], float)
np.save(sys.argv[2]+"/T.npy", T); np.save(sys.argv[2]+"/M.npy", M)
for j, m in enumerate(METRICS):
    nn = ~np.isnan(M[:,j]); best=[]
    for a in range(8):
        for b in range(8):
            if a==b: continue
            d = (T[:,b]-T[:,a])/60
            ok = nn & ~np.isnan(d)
            if ok.sum()==0: continue
            close = np.abs(d[ok]-M[ok,j]) < 0.01
            best.append((close.mean(), ok.sum(), close.sum(), names[a], names[b]))
    best.sort(reverse=True)
    print(f"metric {m}: nonnull={nn.sum()} top:", [(f"{x[0]:.4f}", x[1], x[3]+"->"+x[4]) for x in best[:3]])
