"""Quantiles for amount/fee/distance, fee-rate formulas, drivers deliveries/day, benchmark replications."""
import sys; sys.path.insert(0, sys.argv[1])
from common import *
import numpy as np
con = connect()
q = [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
def qs(sql):
    x = np.array([r[0] for r in con.execute(sql).fetchall()], float); x = x[~np.isnan(x)]
    return f"n={len(x)} mean={x.mean():.2f} " + " ".join(f"p{int(p*100)}={v:.2f}" for p, v in zip(q, np.quantile(x, q)))
print("order_amount FINISHED:", qs("select order_amount from orders where order_status='FINISHED'"))
print("order_delivery_fee:", qs("select order_delivery_fee from orders"))
print("order_delivery_cost non-null:", qs("select order_delivery_cost from orders where order_delivery_cost is not null"))
print("payment_amount:", qs("select payment_amount from payments"))
print("distance (deliveries):", qs("select delivery_distance_meters from deliveries where delivery_distance_meters is not null"))
print("distance DELIVERED w/ driver:", qs("select delivery_distance_meters from deliveries where delivery_status='DELIVERED' and driver_id is not null"))
# fee rate exactness for ONLINE
rows = con.execute("select payment_method, payment_amount, payment_fee from payments where payment_fee>0").fetchall()
from collections import defaultdict, Counter
rates = defaultdict(Counter)
for m, a, f in rows:
    if a > 0: rates[m][round(f / a, 3)] += 1
for m in ["ONLINE", "DEBIT", "CREDIT", "STORE_DIRECT_PAYMENT", "MONEY"]:
    print("fee/amount mode", m, rates[m].most_common(5), "of", sum(rates[m].values()))
# drivers: deliveries per active day (day = order created UTC date), counting deliveries with driver
r = con.execute("""select d.driver_id, o.order_created_year, o.order_created_month, o.order_created_day, count(*)
  from deliveries d join orders o on o.order_id=d.delivery_order_id where d.driver_id is not null group by 1,2,3,4""").fetchall()
per = defaultdict(list)
for drv, y, m, dd, c in r: per[drv].append(c)
avgs = np.array([np.mean(v) for v in per.values()]); days = np.array([len(v) for v in per.values()]); tot = np.array([sum(v) for v in per.values()])
allc = np.array([c for *_, c in r])
print(f"drivers with deliveries {len(per)}; active days p50={np.median(days)} p90={np.quantile(days,0.9)} max={days.max()}; total deliveries/driver p50={np.median(tot)} p90={np.quantile(tot,0.9)} max={tot.max()}")
print(f"deliveries per driver-day: mean={allc.mean():.2f} p50={np.median(allc)} p90={np.quantile(allc,0.9)} p99={np.quantile(allc,0.99)} max={allc.max()}")
top = sorted(((np.mean(v), k, sum(v), len(v)) for k, v in per.items()), reverse=True)[:5]
print("local212 replica (avg per active created-day, driver not null):", [(k, round(a, 2), s, n) for a, k, s, n in top])
# top drivers share
tt = np.sort(tot)[::-1]; print("top2 drivers share of driver deliveries:", tt[:2].sum() / tt.sum(), "top1% share", tt[:len(tt)//100].sum()/tt.sum())
# local209 replica
print("local209 replica:", con.execute("""select o.store_id, count(distinct o.order_id), count(distinct case when d.delivery_status='DELIVERED' then o.order_id end)
 from orders o left join deliveries d on d.delivery_order_id=o.order_id where o.store_id=(select store_id from orders group by 1 order by count(*) desc limit 1) group by 1""").fetchall())
print("local210 replica (hubs with >20% FINISHED growth Feb->Mar):", con.execute("""with f as (select s.hub_id, sum(o.order_created_month=2) feb, sum(o.order_created_month=3) mar
 from orders o join stores s using(store_id) where o.order_status='FINISHED' group by 1) select count(*), group_concat(hub_id) from f where feb>0 and mar>0 and (mar-feb)*1.0/feb>0.2""").fetchall())
