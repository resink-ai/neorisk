-- name: local269_avg_leaf_total
-- expand packaging_relations from top-level containers to leaves, multiply quantities, sum per (top, leaf), then per top; average
with recursive x(top, id, qty) as (
  select p.id, r.contains_id, r.qty from packaging p join packaging_relations r on r.packaging_id = p.id
   where p.id not in (select contains_id from packaging_relations)
  union all select x.top, r.contains_id, x.qty * r.qty from x join packaging_relations r on r.packaging_id = x.id)
select avg(total) average_total_quantity, group_concat(top || '=' || total) per_top from (
  select top, sum(qty) total from x where id not in (select packaging_id from packaging_relations) group by top);
-- name: local270_top_items_over_500
with recursive x(top, id, qty) as (
  select p.id, r.contains_id, r.qty from packaging p join packaging_relations r on r.packaging_id = p.id
   where p.id not in (select contains_id from packaging_relations)
  union all select x.top, r.contains_id, x.qty * r.qty from x join packaging_relations r on r.packaging_id = x.id)
select t.name container_name, i.name item_name, sum(x.qty) total_quantity from x join packaging t on t.id = x.top join packaging i on i.id = x.id
group by x.top, x.id having sum(x.qty) > 500 order by total_quantity desc;
-- name: local274_order421_avg_picked
select pl.product_id, p.name, count(*) picks, sum(pl.qty) units, avg(pl.qty) avg_units from picking_line pl join products p on p.id = pl.product_id
where pl.order_id = 421 group by 1 order by 1;
-- name: local272_order423_from_picking_line
select pl.product_id, l.warehouse, l.aisle, l.position, pl.qty quantity_to_pick from picking_line pl join locations l on l.id = pl.location_id
where pl.order_id = 423 order by pl.line_no;
-- name: local272_fifo_warehouse1
-- the question's literal rule: FIFO (purchase date, then smaller qty) from warehouse 1 only, per order line cumulatively
with inv as (
  select i.product_id, l.aisle, l.position, i.qty, p.purchased,
   sum(i.qty) over (partition by i.product_id order by p.purchased, i.qty, i.id rows unbounded preceding) cum_inv
  from inventory i join locations l on l.id = i.location_id join purchases p on p.id = i.purchase_id where l.warehouse = 1),
 ol as (select product_id, sum(qty) need from orderlines where order_id = 423 group by 1)
select inv.product_id, inv.aisle, inv.position, min(inv.qty, ol.need - (inv.cum_inv - inv.qty)) quantity_to_pick
from inv join ol on ol.product_id = inv.product_id where inv.cum_inv - inv.qty < ol.need order by inv.product_id, inv.purchased, inv.qty;
-- name: local275_cma_ratio_over_2_all_2017
with s as (select product_id, mth, qty, row_number() over (partition by product_id order by mth) t from monthly_sales where mth >= '2016-01-01'),
 c as (select a.product_id, a.mth, a.qty, a.t,
   ((select avg(qty) from s b where b.product_id = a.product_id and b.t between a.t - 5 and a.t + 6) +
    (select avg(qty) from s b where b.product_id = a.product_id and b.t between a.t - 6 and a.t + 5)) / 2 cma from s a where a.t between 7 and 30)
select product_id, count(*) months_2017, sum(qty / cma > 2) months_over_2, round(min(qty / cma), 3) min_ratio, round(max(qty / cma), 3) max_ratio
from c where mth like '2017%' group by 1 order by 1;
