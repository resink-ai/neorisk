-- name: shipping_limit - approved residual (+/-1h) vs DST regime change between the two (Brazil DST: 2016-10-16..2017-02-19, 2017-10-15..2018-02-18)
with x as (
 select o.order_approved_at a, i.shipping_limit_date s,
   round(((julianday(i.shipping_limit_date)-julianday(o.order_approved_at))*24) - 24*round(julianday(i.shipping_limit_date)-julianday(o.order_approved_at)),2) h
 from olist_order_items i join olist_orders o using(order_id) where o.order_approved_at is not null),
y as (select h, ((a>='2016-10-16' and a<'2017-02-19') or (a>='2017-10-15' and a<'2018-02-18')) da,
             ((s>='2016-10-16' and s<'2017-02-19') or (s>='2017-10-15' and s<'2018-02-18')) ds from x)
select h, da, ds, count(*) from y where h in (-1.0, 1.0, 0.0) group by 1,2,3 order by 1,2,3
