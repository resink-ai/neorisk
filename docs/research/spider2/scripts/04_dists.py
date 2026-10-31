"""Distributions to fit (pure Python, read-only). Usage: python3 -I 04_dists.py"""
import collections
import sqlite3

D = "data/spider2/"
con = sqlite3.connect(f"file:{D}Brazilian_E_Commerce.sqlite?mode=ro", uri=True)
con.execute(f"ATTACH DATABASE 'file:{D}E_commerce.sqlite?mode=ro' AS e")
Q = (0.01, 0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)


def q(sql):
    return con.execute(sql).fetchall()


def quant(xs, qs=Q):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if not n:
        return "n=0"
    out = [f"n={n}", f"mean={sum(xs)/n:.3f}", f"min={xs[0]:.3f}"]
    for p in qs:
        out.append(f"p{int(p*100)}={xs[min(n-1, int(p*(n-1)+0.5))]:.3f}")
    out.append(f"max={xs[-1]:.3f}")
    return "  ".join(out)


def hdr(t):
    print(f"\n### {t}", flush=True)


def counts(rows, total=None):
    total = total or sum(r[-1] for r in rows)
    for r in rows:
        print("  " + " | ".join(str(v) for v in r) + f" | {100*r[-1]/total:.2f}%")


# ---- stage delays
J = "julianday"
hdr("stage delays (hours unless noted), delivered status only, both ts non-null")
pairs = {
    "purchase->approved (h)": f"({J}(order_approved_at)-{J}(order_purchase_timestamp))*24",
    "approved->carrier (d)": f"({J}(order_delivered_carrier_date)-{J}(order_approved_at))",
    "carrier->customer (d)": f"({J}(order_delivered_customer_date)-{J}(order_delivered_carrier_date))",
    "purchase->customer (d)": f"({J}(order_delivered_customer_date)-{J}(order_purchase_timestamp))",
    "purchase->estimated (d)": f"({J}(order_estimated_delivery_date)-{J}(order_purchase_timestamp))",
    "customer - estimated (d, >0 late)": f"({J}(order_delivered_customer_date)-{J}(order_estimated_delivery_date))",
}
for k, expr in pairs.items():
    xs = [r[0] for r in q(f"select {expr} from olist_orders where order_status='delivered'")]
    print(f"  {k}: {quant(xs)}")
hdr("purchase->approved (h) for ALL statuses with approved")
print("  " + quant([r[0] for r in q(f"select ({J}(order_approved_at)-{J}(order_purchase_timestamp))*24 from olist_orders")]))
hdr("share approved within 1 min / 1h / 24h (all with approved)")
print(q(f"""select avg(d<=1.0/60), avg(d<=1), avg(d<=24), avg(d>24*7) from
 (select ({J}(order_approved_at)-{J}(order_purchase_timestamp))*24 d from olist_orders where order_approved_at is not null)"""))
hdr("purchase->approved by payment_type of sequential 1 (h)")
for pt, in q("select distinct payment_type from olist_order_payments"):
    xs = [r[0] for r in q(f"""select ({J}(o.order_approved_at)-{J}(o.order_purchase_timestamp))*24 from olist_orders o
          join olist_order_payments p on p.order_id=o.order_id and p.payment_sequential=1 where p.payment_type='{pt}'""")]
    print(f"  {pt}: {quant(xs, (0.25, 0.5, 0.75, 0.9))}")
hdr("estimated delivery: days from purchase date (integer days)")
counts(q(f"""select cast({J}(order_estimated_delivery_date)-{J}(date(order_purchase_timestamp)) as int) d, count(*) from olist_orders group by d order by count(*) desc limit 12"""), 99441)

hdr("shipping_limit_date offsets (days) vs purchase and approved, per item")
xs = q(f"""select ({J}(i.shipping_limit_date)-{J}(o.order_purchase_timestamp)), ({J}(i.shipping_limit_date)-{J}(o.order_approved_at))
         from olist_order_items i join olist_orders o using(order_id)""")
print("  limit-purchase: " + quant([a for a, b in xs]))
print("  limit-approved: " + quant([b for a, b in xs]))
hdr("shipping_limit mm:ss equals approved mm:ss / purchase mm:ss (per item)")
print(q("""select avg(substr(i.shipping_limit_date,15)=substr(o.order_approved_at,15)), avg(substr(i.shipping_limit_date,15)=substr(o.order_purchase_timestamp,15)),
          avg(substr(i.shipping_limit_date,12)=substr(o.order_approved_at,12)), avg(substr(i.shipping_limit_date,12)=substr(o.order_purchase_timestamp,12)), count(*)
          from olist_order_items i join olist_orders o using(order_id) where o.order_approved_at is not null"""))
hdr("shipping_limit - approved, whole-day offsets when hh:mm:ss equal (top)")
counts(q("""select cast(round(julianday(i.shipping_limit_date)-julianday(o.order_approved_at)) as int) d, count(*) from olist_order_items i join olist_orders o using(order_id)
          where substr(i.shipping_limit_date,12)=substr(o.order_approved_at,12) group by d order by 2 desc limit 10"""))
hdr("shipping_limit vs approved: hh:mm:ss differs -- what is the difference (hours, frac part)")
counts(q("""select round(((julianday(i.shipping_limit_date)-julianday(o.order_approved_at))*24) - 24*round(julianday(i.shipping_limit_date)-julianday(o.order_approved_at)),2) h, count(*) from olist_order_items i join olist_orders o using(order_id)
          where o.order_approved_at is not null and substr(i.shipping_limit_date,12)<>substr(o.order_approved_at,12) group by h order by 2 desc limit 10"""))

hdr("review_creation_date (date) - delivered_customer date (days), delivered orders")
print("  " + quant([r[0] for r in q(f"""select {J}(r.review_creation_date)-{J}(date(o.order_delivered_customer_date)) from olist_order_reviews r join olist_orders o using(order_id) where o.order_delivered_customer_date is not null""")]))
hdr("top review_creation - delivered offsets")
counts(q(f"""select cast({J}(r.review_creation_date)-{J}(date(o.order_delivered_customer_date)) as int) d, count(*) from olist_order_reviews r join olist_orders o using(order_id) where o.order_delivered_customer_date is not null group by d order by 2 desc limit 8"""), 96359)
hdr("review_creation - estimated date (days), orders NOT delivered")
print("  " + quant([r[0] for r in q(f"""select {J}(r.review_creation_date)-{J}(o.order_estimated_delivery_date) from olist_order_reviews r join olist_orders o using(order_id) where o.order_delivered_customer_date is null""")]))
hdr("review_creation - purchase (days), orders NOT delivered")
print("  " + quant([r[0] for r in q(f"""select {J}(r.review_creation_date)-{J}(o.order_purchase_timestamp) from olist_order_reviews r join olist_orders o using(order_id) where o.order_delivered_customer_date is null""")]))
hdr("review answer delay (h) = answer - creation")
print("  " + quant([r[0] for r in q(f"select ({J}(review_answer_timestamp)-{J}(review_creation_date))*24 from olist_order_reviews")]))

# ---- volumes
hdr("orders per customer_unique_id")
counts(q("""select c, count(*) from (select c.customer_unique_id u, count(*) c from olist_orders o join olist_customers c using(customer_id) group by u) group by c order by c"""))
hdr("items per order (orders with items)")
counts(q("select n, count(*) from (select count(*) n from olist_order_items group by order_id) group by n order by n"))
hdr("distinct products per order")
counts(q("select n, count(*) from (select count(distinct product_id) n from olist_order_items group by order_id) group by n order by n limit 6"))
hdr("distinct sellers per order")
counts(q("select n, count(*) from (select count(distinct seller_id) n from olist_order_items group by order_id) group by n order by n"))
hdr("price / freight per item, order totals")
print("  price: " + quant([r[0] for r in q("select price from olist_order_items")]))
print("  freight: " + quant([r[0] for r in q("select freight_value from olist_order_items")]))
print("  freight/price: " + quant([r[0] for r in q("select freight_value/price from olist_order_items")]))
print("  order items total (price+freight): " + quant([r[0] for r in q("select sum(price+freight_value) from olist_order_items group by order_id")]))
print("  order payment total: " + quant([r[0] for r in q("select sum(payment_value) from olist_order_payments group by order_id")]))
print("  corr-ish: freight by weight bucket p50:")
for lo, hi in ((0, 500), (500, 2000), (2000, 10000), (10000, 1e9)):
    xs = [r[0] for r in q(f"select i.freight_value from olist_order_items i join olist_products p using(product_id) where p.product_weight_g>={lo} and p.product_weight_g<{hi}")]
    print(f"    weight [{lo},{hi}): {quant(xs, (0.5, 0.9))}")
hdr("cents exactness of money columns")
print(q("""select sum(abs(price*100-round(price*100))>1e-6), sum(abs(freight_value*100-round(freight_value*100))>1e-6) from olist_order_items"""),
      q("select sum(abs(payment_value*100-round(payment_value*100))>1e-6) from olist_order_payments"))

hdr("payment rows per order")
counts(q("select n, count(*) from (select count(*) n from olist_order_payments group by order_id) group by n order by n limit 8"))
hdr("payment_type share (rows)")
counts(q("select payment_type, count(*) from olist_order_payments group by 1 order by 2 desc"))
hdr("payment_type mix per order (distinct types)")
counts(q("select t, count(*) from (select order_id, group_concat(distinct payment_type) t from (select * from olist_order_payments order by payment_type) group by order_id) group by t order by 2 desc limit 8"))
hdr("installments x type")
counts(q("select payment_type, payment_installments, count(*) from olist_order_payments group by 1,2 having count(*)>=100 order by 1,2"), 103886)
hdr("credit_card installments quantiles")
print("  " + quant([r[0] for r in q("select payment_installments from olist_order_payments where payment_type='credit_card'")]))
hdr("multi-row payments: what types are the extra rows")
counts(q("select payment_type, count(*) from olist_order_payments where order_id in (select order_id from olist_order_payments group by 1 having count(*)>1) group by 1 order by 2 desc"))
hdr("orders where pay total > items total: installments of payment rows")
print(q("""with it as (select order_id, sum(price+freight_value) t from olist_order_items group by 1), pa as (select order_id, sum(payment_value) t, max(payment_installments) mi, group_concat(distinct payment_type) ty from olist_order_payments group by 1)
          select avg(mi>1), count(*) from it join pa using(order_id) where pa.t-it.t>0.01"""))

hdr("review score")
counts(q("select review_score, count(*) from olist_order_reviews group by 1 order by 1"))
hdr("review score by late delivery (delivered)")
counts(q("""select late, review_score, count(*) from (select (o.order_delivered_customer_date>o.order_estimated_delivery_date) late, r.review_score from olist_order_reviews r join olist_orders o using(order_id) where o.order_delivered_customer_date is not null) group by 1,2"""), 96359)
hdr("mean score by status")
print(q("select o.order_status, round(avg(review_score),3), count(*) from olist_order_reviews r join olist_orders o using(order_id) group by 1"))
hdr("comment presence by score")
print(q("select review_score, round(avg(review_comment_message is not null),3), round(avg(review_comment_title is not null),3) from olist_order_reviews group by 1"))

hdr("seasonality: weekday (0=Sun) of purchase")
counts(q("select strftime('%w',order_purchase_timestamp) w, count(*) from olist_orders group by w"))
hdr("seasonality: hour of purchase")
counts(q("select strftime('%H',order_purchase_timestamp) h, count(*) from olist_orders group by h"))
hdr("daily orders 2017-01-01..2018-08-31: quantiles and top days")
xs = [r[0] for r in q("select count(*) from olist_orders where order_purchase_timestamp between '2017-01-01' and '2018-08-31 23:59:59' group by date(order_purchase_timestamp)")]
print("  " + quant(xs))
print("  top:", q("select date(order_purchase_timestamp) d, count(*) from olist_orders group by d order by 2 desc limit 5"))
print("  days with 0 orders between first and last:", q("""with recursive d(x) as (select '2016-09-04' union all select date(x,'+1 day') from d where x<'2018-10-17')
     select count(*) from d where x not in (select date(order_purchase_timestamp) from olist_orders)"""))
print("  gap list (>=3 consecutive zero days):", q("""with recursive d(x) as (select '2016-09-04' union all select date(x,'+1 day') from d where x<'2018-10-17')
     select min(x), max(x), count(*) from (select x, julianday(x) - row_number() over (order by x) g from d where x not in (select date(order_purchase_timestamp) from olist_orders)) group by g having count(*)>=3"""))
hdr("approved timestamps by hour (batch approval?)")
counts(q("select strftime('%H',order_approved_at) h, count(*) from olist_orders where order_approved_at is not null group by h"))
hdr("carrier handoff by weekday (0=Sun)")
counts(q("select strftime('%w',order_delivered_carrier_date) w, count(*) from olist_orders where order_delivered_carrier_date is not null group by w"))
hdr("customer delivery by weekday (0=Sun)")
counts(q("select strftime('%w',order_delivered_customer_date) w, count(*) from olist_orders where order_delivered_customer_date is not null group by w"))

hdr("seller concentration (items / revenue)")
rows = q("select seller_id, count(*), sum(price) from olist_order_items group by 1 order by 3 desc")
tot_n = sum(r[1] for r in rows); tot_r = sum(r[2] for r in rows); n = len(rows)
for frac in (0.01, 0.05, 0.1, 0.2):
    k = max(1, int(n * frac))
    top = sorted(rows, key=lambda r: -r[2])[:k]
    topn = sorted(rows, key=lambda r: -r[1])[:k]
    print(f"  top {frac:.0%} sellers ({k}): revenue share {sum(r[2] for r in top)/tot_r:.3f}, item share {sum(r[1] for r in topn)/tot_n:.3f}")
print("  items per seller: " + quant([r[1] for r in rows]))
r_sorted = sorted(r[2] for r in rows)
gini = 1 - 2 * sum((i + 0.5) * 0 + sum(r_sorted[: i + 1]) for i in range(0)) if False else None
cum = 0; area = 0
for v in r_sorted:
    cum += v; area += cum
gini = 1 - 2 * area / (n * tot_r) + 1 / n
print(f"  revenue Gini over sellers: {gini:.3f}")
print("  orders per seller: " + quant([r[0] for r in q("select count(distinct order_id) from olist_order_items group by seller_id")]))
hdr("product concentration")
rows = q("select product_id, count(*) from olist_order_items group by 1 order by 2 desc")
print("  items per product: " + quant([r[1] for r in rows]))
k = int(len(rows) * 0.01); print(f"  top 1% products ({k}) item share: {sum(r[1] for r in rows[:k]) / sum(r[1] for r in rows):.3f}")
print("  products sold once:", sum(1 for r in rows if r[1] == 1))
print("  products per seller: " + quant([r[0] for r in q("select count(distinct product_id) from olist_order_items group by seller_id")]))
print("  sellers per product: ", q("select n, count(*) from (select count(distinct seller_id) n from olist_order_items group by product_id) group by n order by n limit 5"))
hdr("category share of items (top 15, english)")
counts(q("""select coalesce(t.product_category_name_english, p.product_category_name, 'NULL') c, count(*) from olist_order_items i join olist_products p using(product_id)
           left join product_category_name_translation t using(product_category_name) group by c order by 2 desc limit 15"""), 112650)
print("  distinct categories (non-null):", q("select count(distinct product_category_name) from olist_products"))

hdr("geography: customer state share (orders)")
counts(q("select customer_state, count(*) from olist_customers group by 1 order by 2 desc limit 10"), 99441)
hdr("geography: seller state share (items)")
counts(q("select s.seller_state, count(*) from olist_order_items i join olist_sellers s using(seller_id) group by 1 order by 2 desc limit 8"), 112650)
hdr("same-state seller/customer share (items)")
print(q("""select avg(s.seller_state=c.customer_state), count(*) from olist_order_items i join olist_sellers s using(seller_id) join olist_orders o using(order_id) join olist_customers c using(customer_id)"""))
hdr("delivery days by customer state (delivered) p50/p90")
for st, in q("select customer_state from olist_customers group by 1 order by count(*) desc limit 6"):
    xs = [r[0] for r in q(f"""select julianday(order_delivered_customer_date)-julianday(order_purchase_timestamp) from olist_orders o join olist_customers c using(customer_id) where c.customer_state='{st}' and order_status='delivered'""")]
    print(f"  {st}: {quant(xs, (0.5, 0.9))}")
print("  distinct customer zips/cities/states:", q("select count(distinct customer_zip_code_prefix), count(distinct customer_city), count(distinct customer_state) from olist_customers"))
print("  distinct seller zips/cities/states:", q("select count(distinct seller_zip_code_prefix), count(distinct seller_city), count(distinct seller_state) from olist_sellers"))

hdr("customer arrival: first-order month of customer_unique_id; repeat gap (days)")
xs = q("""select c.customer_unique_id, o.order_purchase_timestamp from olist_orders o join olist_customers c using(customer_id) order by 1, 2""")
gaps = []; prev = None
import datetime as dt
for u, t in xs:
    tt = dt.datetime.fromisoformat(t)
    if prev and prev[0] == u:
        gaps.append((tt - prev[1]).total_seconds() / 86400)
    prev = (u, tt)
print("  gap between consecutive orders of same unique customer (d): " + quant(gaps))
print("  share of repeat gaps < 1 hour:", sum(g < 1 / 24 for g in gaps) / len(gaps))

hdr("seller first/last sale span and activity")
print("  seller active span (d): " + quant([r[0] for r in q("""select julianday(max(o.order_purchase_timestamp))-julianday(min(o.order_purchase_timestamp)) from olist_order_items i join olist_orders o using(order_id) group by seller_id""")]))
print("  new sellers per month (first sale):", q("""select m, count(*) from (select substr(min(o.order_purchase_timestamp),1,7) m from olist_order_items i join olist_orders o using(order_id) group by seller_id) group by m order by m"""))

hdr("product dims")
for c in ("product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_photos_qty", "product_name_lenght", "product_description_lenght"):
    print(f"  {c}: " + quant([r[0] for r in q(f"select {c} from olist_products")], (0.05, 0.5, 0.95)))

# ---- leads funnel
hdr("leads: MQL per month")
print("  ", q("select substr(first_contact_date,1,7) m, count(*) from e.leads_qualified group by m order by m"))
hdr("leads: conversion by origin")
print("  ", q("""select coalesce(origin,'NULL'), count(*), sum(mql_id in (select mql_id from e.leads_closed)), round(avg(mql_id in (select mql_id from e.leads_closed)),4) from e.leads_qualified group by 1 order by 2 desc"""))
hdr("leads: days first_contact -> won")
print("  " + quant([r[0] for r in q("select julianday(won_date)-julianday(first_contact_date) from e.leads_closed join e.leads_qualified using(mql_id)")]))
hdr("leads: won per month")
print("  ", q("select substr(won_date,1,7), count(*) from e.leads_closed group by 1 order by 1"))
hdr("leads_closed categorical columns")
for c in ("business_segment", "lead_type", "lead_behaviour_profile", "business_type", "has_company", "has_gtin", "average_stock"):
    print(f"  {c}: ", q(f"select {c}, count(*) from e.leads_closed group by 1 order by 2 desc limit 8"))
print("  distinct sdr, sr, landing pages:", q("select count(distinct sdr_id), count(distinct sr_id) from e.leads_closed"), q("select count(distinct landing_page_id) from e.leads_qualified"))
print("  declared_monthly_revenue>0:", q("select count(*), min(declared_monthly_revenue), max(declared_monthly_revenue) from e.leads_closed where declared_monthly_revenue>0"))
print("  declared_product_catalog_size non-null:", q("select count(*), min(declared_product_catalog_size), max(declared_product_catalog_size) from e.leads_closed where declared_product_catalog_size is not null"))
hdr("leads: won sellers who sold, days won -> first sale")
print("  " + quant([r[0] for r in q("""select julianday(min(o.order_purchase_timestamp))-julianday(lc.won_date) from e.leads_closed lc join olist_order_items i on i.seller_id=lc.seller_id join olist_orders o using(order_id) group by lc.seller_id""")]))
print("  items sold by lead-sourced sellers:", q("select count(*) from olist_order_items where seller_id in (select seller_id from e.leads_closed)"))
