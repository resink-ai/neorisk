"""Brute force integer per-moment offsets o_k in a set so that round((t_b+o_b - t_a-o_a)/60, 2) == metric for all metrics."""
import sys, itertools; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
W = sys.argv[2]; T = np.load(W+"/T.npy"); M = np.load(W+"/M.npy")
i = {m: k for k, m in enumerate(MOMENTS)}
PAIRS = [("ready","collected"),("in_expedition","delivering"),("created","ready"),("ready","in_expedition"),
         ("ready","delivering"),("delivering","END"),("created","END")]
rng = np.random.default_rng(1); idx = rng.choice(len(T), 5000, replace=False)
def ok(t, m, offs):
    end = i["delivered"] if not np.isnan(t[i["delivered"]]) else i["finished"]
    used = sorted({i[a] for a, b in PAIRS} | {i[b] for a, b in PAIRS if b != "END"} | {end})
    used = [k for k in used if not np.isnan(t[k])]
    pos = {k: n for n, k in enumerate(used)}
    for combo in itertools.product(offs, repeat=len(used)):
        good = True
        for j, (a, b) in enumerate(PAIRS):
            if np.isnan(m[j]): continue
            ka, kb = i[a], end if b == "END" else i[b]
            d = (t[kb] + combo[pos[kb]] - t[ka] - combo[pos[ka]]) / 60
            if abs(round(d, 2) - m[j]) > 1e-6 and abs(np.round(d + 1e-9, 2) - m[j]) > 1e-6: good = False; break
        if good: return True
    return False
for offs in [(0,), (0, 1), (-1, 0, 1)]:
    r = [ok(T[k], M[k], offs) for k in idx]
    print("offsets", offs, "feasible share", np.mean(r))
