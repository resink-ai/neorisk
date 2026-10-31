"""Which order moment best explains delivery_id / payment_id ordering (to timestamp child events)."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
W = sys.argv[2]; T = np.load(W+"/T.npy")
con = connect(); oid = np.array([r[0] for r in con.execute("select order_id from orders").fetchall()])
pos = {o: k for k, o in enumerate(oid)}
for tab, idc, ocol in [("deliveries","delivery_id","delivery_order_id"),("payments","payment_id","payment_order_id")]:
    rr = np.array(con.execute(f"select {idc}, {ocol} from {tab} order by {idc}").fetchall())
    P = np.array([pos[o] for o in rr[:, 1]])
    for k, m in enumerate(MOMENTS):
        t = T[P, k]; ok = ~np.isnan(t)
        tt = t[ok]
        nd = np.mean(np.diff(tt) >= 0)
        # inversions magnitude: share of rows whose time is < running max by > 60s
        runmax = np.maximum.accumulate(tt); lag = runmax - tt
        print(f"{tab} by {m}: rows {ok.sum()}, consecutive nondecreasing {nd:.4f}, lag>60s {np.mean(lag>60):.4f}, lag>600s {np.mean(lag>600):.4f}")
    # within-order: multiple deliveries/payments ids consecutive?
    _, first = np.unique(rr[:, 1], return_index=True)
