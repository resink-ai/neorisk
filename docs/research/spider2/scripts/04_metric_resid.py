"""Residuals of metric vs moment differences; null rules; transit/cycle with coalesce(delivered, finished)."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
W = sys.argv[2]; T = np.load(W+"/T.npy"); M = np.load(W+"/M.npy")
i = {m: k for k, m in enumerate(MOMENTS)}
end = np.where(np.isnan(T[:, i["delivered"]]), T[:, i["finished"]], T[:, i["delivered"]])
rules = {"collected_time": ("ready", "collected"), "paused_time": ("in_expedition", "delivering"),
         "production_time": ("created", "ready"), "walking_time": ("ready", "in_expedition"),
         "expediton_speed_time": ("ready", "delivering"), "transit_time": ("delivering", "END"),
         "cycle_time": ("created", "END")}
for j, m in enumerate(METRICS):
    a, b = rules[m]
    tb = end if b == "END" else T[:, i[b]]
    d = (tb - T[:, i[a]]) / 60
    mn, dn = ~np.isnan(M[:, j]), ~np.isnan(d)
    both = mn & dn
    r = d[both] - M[both, j]
    print(f"{m} = ({b} - {a})/60: metric nonnull {mn.sum()}, diff nonnull {dn.sum()}, metric-only {(mn&~dn).sum()}, diff-only {(dn&~mn).sum()}")
    print(f"   |resid|<0.01: {np.mean(np.abs(r)<0.01):.4f}  <1/60: {np.mean(np.abs(r)<1/60+1e-9):.4f}  <1min: {np.mean(np.abs(r)<1.0001):.4f}  max|r| {np.abs(r).max():.3f}")
    print(f"   resid quantiles(min) {np.round(np.quantile(r,[0,0.01,0.25,0.5,0.75,0.99,1]),4)}")
    # decimals in metric values
    v = M[both, j]
    dec = np.round(v*1e6) % 1e4
    print(f"   metric sample {np.round(v[:6],6)}  diff sample {np.round(d[both][:6],6)}")
    neg = (M[mn, j] < 0).sum(); print(f"   negative metric values: {neg}")
