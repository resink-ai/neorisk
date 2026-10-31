"""Histogram of metric*60 - integer-second diff (seconds), per metric."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
W = sys.argv[2]; T = np.load(W+"/T.npy"); M = np.load(W+"/M.npy")
i = {m: k for k, m in enumerate(MOMENTS)}
end = np.where(np.isnan(T[:, i["delivered"]]), T[:, i["finished"]], T[:, i["delivered"]])
PAIRS = [("ready","collected"),("in_expedition","delivering"),("created","ready"),("ready","in_expedition"),
         ("ready","delivering"),("delivering","END"),("created","END")]
for j,(a,b) in enumerate(PAIRS):
    tb = end if b=="END" else T[:, i[b]]
    sec = tb - T[:, i[a]]; ok = ~np.isnan(sec) & ~np.isnan(M[:, j])
    r = np.round(M[ok, j]*60 - sec[ok], 1)
    u, c = np.unique(r, return_counts=True)
    print(METRICS[j], " ".join(f"{x:+.1f}s:{y}" for x, y in zip(u, c) if y > 50))
# if metric = trunc-to-2dp vs round?
