"""Exactness of metric = round(diff/60, 2); diff-only (metric missing) cases; created_* mismatches."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
W = sys.argv[2]; T = np.load(W+"/T.npy"); M = np.load(W+"/M.npy")
con = connect(); cols, rows = load_orders(con); ix = {c: k for k, c in enumerate(cols)}
status = np.array([r[ix["order_status"]] for r in rows])
i = {m: k for k, m in enumerate(MOMENTS)}
end = np.where(np.isnan(T[:, i["delivered"]]), T[:, i["finished"]], T[:, i["delivered"]])
rules = {"collected_time": ("ready", "collected"), "paused_time": ("in_expedition", "delivering"),
         "production_time": ("created", "ready"), "walking_time": ("ready", "in_expedition"),
         "expediton_speed_time": ("ready", "delivering"), "transit_time": ("delivering", "END"),
         "cycle_time": ("created", "END")}
for j, m in enumerate(METRICS):
    a, b = rules[m]; tb = end if b == "END" else T[:, i[b]]
    sec = tb - T[:, i[a]]; d = sec / 60
    both = ~np.isnan(M[:, j]) & ~np.isnan(d)
    ex = np.round(d[both], 2) == np.round(M[both, j], 2)
    v = M[both, j]; more2 = np.abs(v*100 - np.round(v*100)) > 1e-6
    # implied seconds: metric*60 ; can any integer-second diff produce the metric? metric hits 2dp grid of 1/60 multiples
    print(f"{m}: exact round2 match {ex.mean():.4f} ({(~ex).sum()} mismatches); metric with >2 decimals: {more2.sum()}")
    do = ~np.isnan(d) & np.isnan(M[:, j])
    if do.sum():
        print(f"   diff present but metric null: {do.sum()} statuses {dict(zip(*np.unique(status[do], return_counts=True)))} "
              f"diff<0: {(sec[do]<0).sum()} diff sample(min) {np.round(d[do][:8],2)}  delivered-null among them {np.isnan(T[do, i['delivered']]).sum()}")
# Is there a rounding-consistent integer-second solution? check consistency: metric value m, |m*60 - sec| <= 30s?
# created_* mismatches
import datetime as dt
for r, t in zip(rows, T[:, 0]):
    c = dt.datetime(1970,1,1)+dt.timedelta(seconds=t)
    if r[ix["order_created_hour"]] != c.hour or r[ix["order_created_day"]] != c.day:
        print("created mismatch", r[ix["order_id"]], r[ix["order_moment_created"]], "hour", r[ix["order_created_hour"]], "min", r[ix["order_created_minute"]], "day", r[ix["order_created_day"]], "month", r[ix["order_created_month"]])
