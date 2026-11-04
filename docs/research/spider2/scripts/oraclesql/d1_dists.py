"""Distributions for stage 2, plus the broken-view check. Usage: python3 -I d1_dists.py data/spider2/oracle_sql.sqlite (mode=ro)"""
import sqlite3, sys, statistics as st
from datetime import date
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchall()
def qs(xs, ps=(0, .1, .25, .5, .75, .9, 1)):
    xs = sorted(xs); return {p: xs[min(len(xs) - 1, int(p * (len(xs) - 1) + .5))] for p in ps}
print("## purchases qty quantiles", qs([r[0] for r in q("select qty from purchases")]))
print("## purchases cost quantiles", qs([r[0] for r in q("select cost from purchases")]))
gaps = []
for (pid,) in q("select distinct product_id from purchases"):
    ds = [date.fromisoformat(r[0]) for r in q(f"select purchased from purchases where product_id={pid} order by purchased")]
    gaps += [(b - a).days for a, b in zip(ds, ds[1:])]
print("## inter-purchase gap per product (days)", qs(gaps), "mean", round(st.mean(gaps), 2))
from collections import Counter
print("   gap counts", sorted(Counter(gaps).items()))
print("## purchases per month (all products)", sorted(Counter(r[0] for r in q("select count(*) from purchases group by strftime('%Y-%m', purchased)")).items()))
print("## purchases per brewery", q("select brewery_id, count(*), sum(qty), sum(cost) from purchases group by 1"))
print("## monthly_sales qty quantiles", qs([r[0] for r in q("select qty from monthly_sales")]))
print("## monthly_sales by calendar month (sum over products and years)")
for m, s in q("select strftime('%m', mth), sum(qty) from monthly_sales group by 1"): print("  ", m, s)
print("## monthly_sales by product per year", q("select product_id, group_concat(s, '/') from (select product_id, strftime('%Y', mth) y, sum(qty) s from monthly_sales group by 1, 2 order by 1, 2) group by 1"))
print("## monthly_budget by calendar month, 6520 and 6600", q("select product_id, group_concat(cast(qty as integer), ',') from (select * from monthly_budget order by product_id, mth) group by 1"))
print("## orderline qty", sorted(r[0] for r in q("select qty from orderlines")))
print("## orderline amount/qty (unit price) quantiles", qs([r[0] / r[1] for r in q("select amount, qty from orderlines")]))
print("## orders per customer", q("select customer_id, count(*) from orders group by 1"))
og = [r[0] for r in q("select cast(julianday(ordered) - julianday(lag(ordered) over (order by ordered)) as integer) from orders") if r[0] is not None]
print("## inter-order gap days", og)
print("## lines per order", sorted(Counter(r[0] for r in q("select count(*) from orderlines group by order_id")).items()))
print("## picking: lines per list", q("select picklist_id, count(*), sum(qty) from picking_line group by 1"))
print("## picking: created -> first log seconds", q("select pl.id, cast(round((julianday(min(g.log_time)) - julianday(pl.created)) * 86400) as integer) from picking_list pl join picking_log g on g.picklist_id = pl.id group by 1"))
print("## picking: order -> picklist created (days)", q("select l.order_id, round(julianday(pl.created) - julianday(o.ordered), 2) from picking_line l join picking_list pl on pl.id = l.picklist_id join orders o on o.id = l.order_id group by 1"))
print("## picking_line qty", sorted(r[0] for r in q("select qty from picking_line")))
vg = [r[0] for r in q("select cast(round((julianday(visit_time) - julianday(lag(visit_time) over (partition by client_ip order by visit_time))) * 86400) as integer) from web_page_visits") if r[0] is not None]
print("## visit gaps seconds (per ip)", sorted(vg))
print("## visit page mix", q("select page_no, count(*) from web_page_visits group by 1"))
print("## counter daily delta quantiles by page")
for (pg,) in q("select distinct page_no from web_counter_hist"):
    d = [r[0] for r in q(f"select counter - lag(counter) over (order by day) from web_counter_hist where page_no = {pg}") if r[0] is not None]
    print("  page", pg, qs(d), "mean", round(st.mean(d), 1))
print("## ticker daily change", [round(r[0], 1) for r in q("select price - lag(price) over (order by day) from ticker") if r[0] is not None])
print("## device mix share", q("select day, round(1.0*pc/(pc+tablet+phone),3), round(1.0*tablet/(pc+tablet+phone),3), round(1.0*phone/(pc+tablet+phone),3) from web_devices"))
print("## hire period lengths (days, closed only)", sorted(r[0] for r in q("select cast(julianday(end_) - julianday(start_) as integer) from emp_hire_periods where end_ is not null")))
print("## broken view emp_hire_periods_with_name:")
try:
    print(con.execute("select count(*) from emp_hire_periods_with_name").fetchall())
except Exception as e:
    print("   ERROR:", type(e).__name__, e)
