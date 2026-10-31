-- name: multi_address_customer
select customerid, shipname, shipaddress, shipcity, count(*) from orders where customerid in
 (select customerid from orders group by 1 having count(distinct shipname||shipaddress||shipcity||coalesce(shipregion,'')||coalesce(shippostalcode,'')||shipcountry) > 1) group by 1,2,3,4;
-- name: discount_values
select discount, printf('%.17g', discount) exact, count(*) from order_details group by 1 order by 1;
-- name: quantity_dist
select case when quantity <= 5 then '1-5' when quantity <= 10 then '6-10' when quantity <= 20 then '11-20' when quantity <= 30 then '21-30' when quantity <= 50 then '31-50' when quantity <= 80 then '51-80' else '81+' end b, count(*), min(quantity), max(quantity) from order_details group by 1 order by 3;
-- name: lines_per_order
select k, count(*) orders from (select orderid, count(*) k from order_details group by 1) group by 1 order by 1;
-- name: line_price_vs_list_price
select case when d.unitprice = p.unitprice then 'equal list' when abs(d.unitprice - p.unitprice*0.8) < 0.006 then '0.8 x list' else 'other' end k, count(*) n,
  min(o.orderdate), max(o.orderdate)
from order_details d join products p using(productid) join orders o using(orderid) group by 1;
-- name: price_change_date
-- per product: last date at the old price and first date at the new price
select count(*) products_with_two_prices, min(first_new), max(first_new), min(last_old), max(last_old) from (
 select d.productid, max(case when d.unitprice <> p.unitprice then o.orderdate end) last_old, min(case when d.unitprice = p.unitprice then o.orderdate end) first_new
 from order_details d join products p using(productid) join orders o using(orderid) group by 1 having count(distinct d.unitprice) = 2);
-- name: prices_per_product
select k, count(*) products from (select productid, count(distinct unitprice) k from order_details group by 1) group by 1;
-- name: price_switch_by_orderid
select min(orderid) first_order_all_list, (select max(d.orderid) from order_details d join products p using(productid) where d.unitprice <> p.unitprice) last_order_old_price
from order_details d join products p using(productid) where d.unitprice = p.unitprice;
-- name: freight_stats
select min(freight), max(freight), round(avg(freight),2), sum(freight = 0) zero from orders;
-- name: products_stock
select sum(discontinued) discontinued, sum(unitsinstock = 0) out_of_stock, sum(unitsonorder > 0) on_order, sum(unitsinstock + unitsonorder < reorderlevel) need_reorder, min(unitprice), max(unitprice) from products;
-- name: discontinued_last_order
select p.productid, p.discontinued, max(o.orderdate) last_order from products p join order_details d using(productid) join orders o using(orderid) where p.discontinued = 1 group by 1;
-- name: thresholds
select groupname, rangebottom, typeof(rangebottom), printf('%.17g', rangetop) top, typeof(rangetop) from customergroupthreshold;
-- name: usstates_regions
select stateregion, count(*) from usstates group by 1;
-- name: customer_countries
select country, count(*) from customers group by 1 order by 2 desc limit 8;
-- name: orders_per_customer
select k, count(*) customers from (select customerid, count(*) k from orders group by 1) group by 1 order by 1;
-- name: employees_hire_vs_first_order
select e.employeeid, e.hiredate, min(o.orderdate) first_order from employees e join orders o using(employeeid) group by 1;
-- name: local081_groups
with s as (select o.customerid, sum(d.unitprice * d.quantity) spent from orders o join order_details d using(orderid) where o.orderdate >= '1998-01-01' and o.orderdate < '1999-01-01' group by 1),
g as (select s.customerid, t.groupname from s join customergroupthreshold t on s.spent between t.rangebottom and t.rangetop)
select groupname, count(*) customer_count, round(100.0 * count(*) / (select count(*) from s), 2) pct from g group by 1 order by case groupname when 'Low' then 1 when 'Medium' then 2 when 'High' then 3 else 4 end;
-- name: local081_gap_check
-- customers whose spend falls between a rangetop and the next rangebottom (e.g. 999.99995)
with s as (select o.customerid, sum(d.unitprice * d.quantity) spent from orders o join order_details d using(orderid) where o.orderdate like '1998%' group by 1)
select count(*) customers_1998, sum(not exists (select 1 from customergroupthreshold t where s.spent between t.rangebottom and t.rangetop)) in_gap from s;
-- name: local085_late
with e as (select employeeid, count(*) n, sum(shippeddate >= requireddate) late from orders group by 1 having count(*) > 50)
select employeeid, late, round(100.0 * late / n, 6) pct from e order by pct desc limit 3;
-- name: other_price_ratio
select round(d.unitprice / p.unitprice, 3) ratio, count(*) n, count(distinct productid) products from order_details d join products p using(productid)
where d.unitprice <> p.unitprice group by 1 order by 2 desc limit 8;
-- name: old_price_per_product_constant
select count(*) products, sum(k = 1) one_old_price from (select productid, count(distinct d.unitprice) k from order_details d join products p using(productid) where d.unitprice <> p.unitprice group by 1);
-- name: three_price_products
select productid, d.unitprice, min(orderid), max(orderid), count(*) from order_details d where productid in (select productid from order_details group by 1 having count(distinct unitprice)=3) group by 1,2;
-- name: price_regime_by_orderid
-- is there one cut-over orderid per product? old-price lines after the first list-price line
select count(*) products, sum(late_old > 0) products_with_old_after_new from (
 select p.productid, (select count(*) from order_details d2 where d2.productid=p.productid and d2.unitprice<>p.unitprice and d2.orderid >
   (select min(orderid) from order_details d3 where d3.productid=p.productid and d3.unitprice=p.unitprice)) late_old from products p);
-- name: order_25_lines
select orderid, customerid, orderdate, (select count(*) from order_details d where d.orderid=o.orderid) n from orders o where (select count(*) from order_details d where d.orderid=o.orderid) > 6;
-- name: discount_by_customer_order
-- is discount constant within an order?
select count(*) orders, sum(k = 1) one_discount from (select orderid, count(distinct discount) k from order_details group by 1);
-- name: order_value_quantiles
with v as (select orderid, sum(unitprice*quantity*(1-discount)) net from order_details group by 1), r as (select net, row_number() over (order by net) k, count(*) over () m from v)
select (select net from r where k = m*5/100) p5, (select net from r where k = m/4) p25, (select net from r where k = m/2) p50, (select net from r where k = m*3/4) p75, (select net from r where k = m*9/10) p90, (select net from r where k = m*99/100) p99, (select max(net) from r) mx from r limit 1;
-- name: freight_quantiles
with r as (select freight, row_number() over (order by freight) k, count(*) over () m from orders)
select (select freight from r where k = m/10) p10, (select freight from r where k = m/2) p50, (select freight from r where k = m*9/10) p90, (select freight from r where k = m*99/100) p99 from r limit 1;
-- name: freight_vs_order_value
with v as (select orderid, sum(unitprice*quantity) gross from order_details group by 1)
select round(avg(freight / gross), 4) mean_ratio, count(*) from orders join v using(orderid);
-- name: product_popularity
select k, count(*) products from (select productid, count(*) k from order_details group by 1) group by 1 order by 1;
-- name: category_mix
select c.categoryname, count(*) lines, round(sum(d.unitprice*d.quantity*(1-d.discount)),2) net from order_details d join products p using(productid) join categories c using(categoryid) group by 1 order by 2 desc;
-- name: shipping_country_mix
select shipcountry, count(*) from orders group by 1 order by 2 desc limit 8;
-- name: required_lead_by_customer
select customerid, group_concat(distinct cast(julianday(requireddate)-julianday(orderdate) as int)) leads, count(*) from orders group by 1 having count(distinct cast(julianday(requireddate)-julianday(orderdate) as int)) > 1 limit 10;
-- name: required_lead_customers
select lead, count(distinct customerid) customers, count(*) orders from (select customerid, cast(julianday(requireddate)-julianday(orderdate) as int) lead from orders) group by 1;
-- name: ship_lag_by_shipper
select shipvia, count(*), round(avg(julianday(shippeddate)-julianday(orderdate)),2) mean_days, sum(shippeddate >= requireddate) late from orders where shippeddate is not null group by 1;
-- name: ship_lag_by_year
select substr(orderdate,1,4) y, count(*), round(avg(julianday(shippeddate)-julianday(orderdate)),2) mean_days, sum(shippeddate is null) unshipped from orders group by 1;
