"""Distributions: stage delays, volume by hour/dow/month, concentration, amounts, fees, distance, id monotonicity."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np, datetime as dt
W = sys.argv[2]; T = np.load(W+"/T.npy")
con = connect(); cols, rows = load_orders(con); ix = {c: k for k, c in enumerate(cols)}
st = np.array([r[ix["order_status"]] for r in rows]); oid = np.array([r[ix["order_id"]] for r in rows])
fin = st == "FINISHED"
q = [0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
def qs(x): x = x[~np.isnan(x)]; return f"n={len(x)} " + " ".join(f"p{int(p*100)}={v:.1f}" for p, v in zip(q, np.quantile(x, q))) + f" mean={x.mean():.1f}"
i = {m: k for k, m in enumerate(MOMENTS)}
print("== stage delays, minutes, FINISHED orders, both endpoints non-null")
for a, b in [("created","accepted"),("accepted","ready"),("ready","collected"),("collected","in_expedition"),
             ("in_expedition","delivering"),("ready","delivering"),("delivering","delivered"),("delivering","finished"),
             ("delivered","finished"),("created","finished")]:
    print(f"{a}->{b}:", qs((T[fin, i[b]] - T[fin, i[a]]) / 60))
print("== CANCELED orders: last non-null moment -> created (min)")
can = ~fin
last = np.nanmax(T[can][:, 1:], axis=1)
print("cancel with any later moment:", np.sum(~np.isnan(last)), qs((last - T[can, 0]) / 60))
c = np.array([dt.datetime(1970,1,1)+dt.timedelta(seconds=t) for t in T[:, 0]])
print("== volume by hour (all orders, % )")
h = np.array([x.hour for x in c]); print(" ".join(f"{k}:{100*np.mean(h==k):.1f}" for k in range(24)))
dow = np.array([x.weekday() for x in c]); print("dow Mon..Sun %:", " ".join(f"{100*np.mean(dow==k):.1f}" for k in range(7)))
mo = np.array([x.month for x in c]); print("month counts:", {m: int((mo==m).sum()) for m in range(1,5)}, "finished:", {m: int(((mo==m)&fin).sum()) for m in range(1,5)})
days = np.array([x.date() for x in c]); u, cnt = np.unique(days, return_counts=True)
print("orders/day: n_days", len(u), "min", cnt.min(), "p50", np.median(cnt), "max", cnt.max(), "first", u[0], "last", u[-1])
print("lowest days:", sorted(zip(cnt, u))[:5])
print("cancel rate by month:", {m: round(float(np.mean(~fin[mo==m])),4) for m in range(1,5)})
# id monotonicity
order = np.argsort(T[:, 0], kind="stable")
print("order_id increasing with created (consecutive pairs):", np.mean(np.diff(oid[order]) > 0))
for tab, idc, ocol in [("deliveries","delivery_id","delivery_order_id"),("payments","payment_id","payment_order_id")]:
    rr = np.array(con.execute(f"select {idc}, {ocol} from {tab} order by {idc}").fetchall())
    pos = {o: k for k, o in enumerate(oid)}
    ct = T[[pos[o] for o in rr[:, 1]], 0]
    print(f"{tab}: id order vs order created, consecutive non-decreasing share {np.mean(np.diff(ct) >= 0):.4f}; corr rank {np.corrcoef(np.argsort(np.argsort(ct)), np.arange(len(ct)))[0,1]:.4f}")
