"""Feasibility: do sub-second true moments exist such that text = round/trunc(moment) and metric = round(diff/60,2)?
Difference-constraint system per order, Bellman-Ford. Also inspect metric-null-but-diff-present cases."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
W = sys.argv[2]; T = np.load(W+"/T.npy"); M = np.load(W+"/M.npy")
i = {m: k for k, m in enumerate(MOMENTS)}
PAIRS = [("ready","collected"),("in_expedition","delivering"),("created","ready"),("ready","in_expedition"),
         ("ready","delivering"),("delivering","END"),("created","END")]
def feasible(row_t, row_m, lo_off, hi_off, tol):
    # nodes 0..7 moments, 8 = origin z. x_k - z in [s_k+lo, s_k+hi]
    end = i["delivered"] if not np.isnan(row_t[i["delivered"]]) else i["finished"]
    edges = []  # (u, v, w): x_v - x_u <= w
    Z = 8
    for k in range(8):
        if np.isnan(row_t[k]): continue
        s = row_t[k] - row_t[0] if not np.isnan(row_t[0]) else row_t[k]
        edges.append((Z, k, s + hi_off)); edges.append((k, Z, -(s + lo_off)))
    for j, (a, b) in enumerate(PAIRS):
        if np.isnan(row_m[j]): continue
        ka, kb = i[a], (end if b == "END" else i[b])
        if np.isnan(row_t[ka]) or np.isnan(row_t[kb]): return None
        m = row_m[j] * 60
        edges.append((ka, kb, m + tol)); edges.append((kb, ka, -(m - tol)))
    dist = np.zeros(9)
    for _ in range(9):
        ch = False
        for u, v, w in edges:
            if dist[u] + w < dist[v] - 1e-9: dist[v] = dist[u] + w; ch = True
        if not ch: return True
    return False
rng = np.random.default_rng(0)
idx = rng.choice(len(T), 20000, replace=False)
for name, lo, hi in [("round-to-nearest [-0.5,0.5]", -0.5, 0.5), ("truncate [0,1)", 0.0, 0.999999), ("exact integer secs", 0, 0)]:
    res = [feasible(T[r], M[r], lo, hi, 0.3) for r in idx]
    ok = sum(x is True for x in res); bad = sum(x is False for x in res)
    print(f"{name}: feasible {ok}, infeasible {bad}, n/a {sum(x is None for x in res)} (sample 20000)")
# diff-only inspection
end = np.where(np.isnan(T[:, i["delivered"]]), T[:, i["finished"]], T[:, i["delivered"]])
d = (end - T[:, 0]) / 60
do = ~np.isnan(d) & np.isnan(M[:, 6])
print("cycle diff-only: n", do.sum(), "diff==0:", (d[do]==0).sum(), "diff<0:", (d[do]<0).sum(), ">0:", (d[do]>0).sum())
print("cycle metric present with diff==0:", (~np.isnan(M[:,6]) & (d==0)).sum(), " present with diff<0:", (~np.isnan(M[:,6]) & (d<0)).sum())
tr = (end - T[:, i["delivering"]]) / 60
print("transit metric present with diff<0:", (~np.isnan(M[:,5]) & (tr<0)).sum(), " null with diff<0:", (np.isnan(M[:,5]) & (tr<0)).sum(),
      " present w/ diff<0 & delivered-not-null:", (~np.isnan(M[:,5]) & (tr<0) & ~np.isnan(T[:, i['delivered']])).sum())
