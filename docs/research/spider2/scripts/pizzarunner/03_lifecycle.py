"""Order -> pickup -> delivered/cancelled timing, text formats, registration dates.

Run: python3 -I docs/research/spider2/scripts/pizzarunner/03_lifecycle.py [data/spider2/modern_data.sqlite]
"""
import re
import sqlite3
import statistics as st
import sys
from collections import Counter
from datetime import datetime, timedelta

db = sys.argv[1] if len(sys.argv) > 1 else "data/spider2/modern_data.sqlite"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
F = "%Y-%m-%d %H:%M:%S"

orders = {}
for oid, cid, t in con.execute("SELECT order_id, customer_id, min(order_time) FROM pizza_customer_orders GROUP BY order_id"):
    orders[oid] = (cid, datetime.strptime(t, F))
npz = dict(con.execute("SELECT order_id, count(*) FROM pizza_customer_orders GROUP BY order_id"))
ro = con.execute("SELECT order_id, runner_id, pickup_time, distance, duration, cancellation FROM pizza_runner_orders ORDER BY rowid").fetchall()
reg = {r: datetime.strptime(d, "%Y-%m-%d") for r, d in con.execute("SELECT runner_id, registration_date FROM pizza_runners")}

print("== text formats")
print("distance texts:", [r[3] for r in ro])
print("duration texts:", [r[4] for r in ro])
pat_d = Counter(re.sub(r"[0-9]+(\.[0-9]+)?", "N", r[3]) if r[3] is not None else None for r in ro)
pat_u = Counter(re.sub(r"[0-9]+(\.[0-9]+)?", "N", r[4]) if r[4] is not None else None for r in ro)
print("distance patterns:", dict(pat_d))
print("duration patterns:", dict(pat_u))
print("durations integer-valued:", all(float(re.match(r"[0-9.]+", r[4]).group()) % 1 == 0 for r in ro if r[4]))
print("cancellation texts:", Counter(r[5] for r in ro))
print("null pattern (pickup,distance,duration,cancel) is None:", Counter(tuple(x is None for x in r[2:6]) for r in ro))
print("time text lengths:", Counter(len(t) for (t,) in con.execute(
    "SELECT order_time FROM pizza_customer_orders UNION ALL SELECT pickup_time FROM pizza_runner_orders WHERE pickup_time IS NOT NULL")))
print("seconds == 0 count:", con.execute(
    "SELECT sum(substr(order_time,18,2)='00') FROM pizza_customer_orders").fetchone())

print("\n== lifecycle per order")
gaps, durs, dists, speeds, deliv = [], [], [], [], []
rows = []
for oid, rid, pu, dist, dur, canc in ro:
    cid, ot = orders[oid]
    if pu is None:
        rows.append((oid, rid, cid, ot, None, None, canc))
        continue
    p = datetime.strptime(pu, F)
    d_min = float(re.match(r"[0-9.]+", dur).group())
    km = float(re.match(r"[0-9.]+", dist).group())
    dv = p + timedelta(minutes=d_min)
    gaps.append((p - ot).total_seconds() / 60)
    durs.append(d_min)
    dists.append(km)
    speeds.append(km / (d_min / 60))
    deliv.append((rid, p, dv, oid))
    rows.append((oid, rid, cid, ot, p, dv, canc))
for r in rows:
    print(r[0], "runner", r[1], "cust", r[2], "ordered", r[3], "pickup", r[4], "delivered", r[5], r[6] or "")
print("order->pickup minutes:", [round(g, 2) for g in gaps])
print("  min/median/mean/max:", round(min(gaps), 2), round(st.median(gaps), 2), round(st.mean(gaps), 2), round(max(gaps), 2))
print("prep minutes per pizza (gap / pizzas):", [round(g / npz[o], 2) for g, (_, _, _, o) in zip(gaps, deliv)])
print("pickup before order:", sum(g < 0 for g in gaps))
print("duration min/median/max:", min(durs), st.median(durs), max(durs))
print("distance min/median/max:", min(dists), st.median(dists), max(dists))
print("speed km/h:", [round(s, 1) for s in speeds], "mean", round(st.mean(speeds), 2))
print("pickup date != order date:", sum(1 for r in rows if r[4] and r[4].date() != r[3].date()))

# runner overlap: a runner picking up a new order before the previous delivery ends
by = {}
for rid, p, dv, oid in sorted(deliv):
    by.setdefault(rid, []).append((p, dv, oid))
ov = sum(1 for v in by.values() for a, b in zip(v, v[1:]) if b[0] < a[1])
print("runner overlaps (pickup before own previous delivery):", ov)
print("pickup order == order_id order:", [o for _, _, _, o in sorted(deliv, key=lambda x: x[1])])

print("\n== cancellations")
for r in rows:
    if r[6]:
        print(r[0], r[6], "runner", r[1], "ordered", r[3], "pizzas", npz[r[0]])

print("\n== registration dates")
first = {}
for rid, p, dv, oid in deliv:
    first[rid] = min(first.get(rid, p), p)
for oid, rid, *_ in ro:
    first.setdefault(rid, None)
for rid in sorted(reg):
    f = first.get(rid)
    print("runner", rid, "registered", reg[rid].date(), reg[rid].strftime("%a"),
          "first pickup", f, "days reg->first", None if f is None else (f.date() - reg[rid].date()).days)
first_any = {}
for oid, rid, *_ in ro:
    t = orders[oid][1]
    first_any[rid] = min(first_any.get(rid, t), t)
print("first assigned order_time per runner:", {k: str(v) for k, v in sorted(first_any.items())})
print("assigned before registration:", sum(1 for oid, rid, *_ in ro if orders[oid][1] < reg[rid]))
print("registration day offsets from 2021-01-01:", [(reg[r] - datetime(2021, 1, 1)).days for r in sorted(reg)])
all_t = [t for _, t in orders.values()] + [p for _, p, _, _ in deliv] + [dv for _, _, dv, _ in deliv]
print("max event time (order/pickup/delivery):", max(all_t), " max registration:", max(reg.values()))

print("\n== arrivals")
ots = sorted(t for _, t in orders.values())
print("order dates:", Counter(t.date().isoformat() for t in ots))
print("order hours:", sorted(Counter(t.hour for t in ots).items()))
print("weekday:", Counter(t.strftime("%a") for t in ots))
ia = [(b - a).total_seconds() / 3600 for a, b in zip(ots, ots[1:])]
print("inter-order hours:", [round(x, 2) for x in ia], "median", round(st.median(ia), 2))
print("span days:", (ots[-1] - ots[0]).total_seconds() / 86400)
