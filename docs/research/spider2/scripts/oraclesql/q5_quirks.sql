-- name: purchase_day_rule
-- day of month = product rank (1..10 by id) + 10*(year-2016), clipped to the month's last day
with r as (select id, row_number() over (order by id) k from products)
select count(*) n,
 sum(cast(strftime('%d', p.purchased) as integer) = min(r.k + 10 * (cast(strftime('%Y', p.purchased) as integer) - 2016), cast(strftime('%d', date(p.purchased, 'start of month', '+1 month', '-1 day')) as integer))) rule_ok
from purchases p join r on r.id = p.product_id;
-- name: purchase_day_rule_misses
with r as (select id, row_number() over (order by id) k from products)
select p.id, p.product_id, r.k, p.purchased from purchases p join r on r.id = p.product_id
where cast(strftime('%d', p.purchased) as integer) != min(r.k + 10 * (cast(strftime('%Y', p.purchased) as integer) - 2016), cast(strftime('%d', date(p.purchased, 'start of month', '+1 month', '-1 day')) as integer));
-- name: yearly_purchase_totals_round
select sum(s % 100 = 0) multiple_of_100, count(*) n from (select product_id, strftime('%Y', purchased) y, sum(qty) s from purchases group by 1, 2);
-- name: lots_over_48
select i.*, p.qty purchase_qty from inventory i join purchases p on p.id = i.purchase_id where i.purchase_id in (select purchase_id from inventory where qty > 48 or purchase_id = 729) order by i.purchase_id, i.id;
-- name: lot_split_rule
-- per purchase: lots are floor(qty/48) full cases + remainder?
select sum(ok) rule_ok, count(*) n from (select p.id, (sum(i.qty = 48) = p.qty / 48 and sum(i.qty < 48) = (p.qty % 48 > 0)) ok from purchases p join inventory i on i.purchase_id = p.id group by p.id);
-- name: lot_split_misses
select p.id, p.product_id, p.qty, group_concat(cast(i.qty as integer), '+') lots from purchases p join inventory i on i.purchase_id = p.id group by p.id
having not (sum(i.qty = 48) = p.qty / 48 and sum(i.qty < 48) = (p.qty % 48 > 0));
-- name: inventory_id_interleave
-- inventory ids step by 3 in purchase order, i.e. ids look generated as base + 3*n
select min(id), max(id), count(*), (max(id) - min(id)) / 3 + 1 slots from inventory;
-- name: orderline_amount_vs_list
select l.product_id, l.order_id, l.qty, l.amount, round(l.amount / l.qty, 4) unit from orderlines l order by 1, 2;
-- name: monthly_sales_zeros_by_product
select product_id, count(*) from monthly_sales where qty = 0 group by 1;
-- name: monthly_sales_max
select * from monthly_sales order by qty desc limit 5;
-- name: picklist_alone_vs_inventory
-- each picklist on its own against inventory: locations where it picks more than the lot holds, and locations emptied
select l.picklist_id, count(*) locations, sum(s.picked > i.qty) overdrawn, sum(s.picked = i.qty) emptied, sum(s.picked < i.qty) partly
from (select picklist_id, location_id, sum(qty) picked from picking_line group by 1, 2) s
join inventory i on i.location_id = s.location_id join (select distinct picklist_id from picking_line) l on l.picklist_id = s.picklist_id group by 1;
-- name: both_picklists_vs_inventory
select count(*) locations, sum(picked > inv) overdrawn from (select location_id, sum(qty) picked, (select qty from inventory i where i.location_id = p.location_id) inv from picking_line p group by 1);
-- name: sales_2018_vs_lots_2018
-- 2018 lots are all still whole in inventory although 2018 monthly sales are non-zero
select (select sum(qty) from monthly_sales where mth like '2018%') sales_2018, (select sum(qty) from purchases where purchased like '2018%') bought_2018,
 (select sum(i.qty) from inventory i join purchases p on p.id = i.purchase_id where p.purchased like '2018%') in_stock_from_2018;
