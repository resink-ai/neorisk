-- name: due_minus_ship
select julianday(duedate)-julianday(shipdate) d, count(*) from salesorderheader group by 1;

-- name: max_online_orders_per_customer
select n, count(*) customers from (select customerid, count(*) n from salesorderheader where onlineorderflag='t' group by 1) where n>=7 group by 1 order by 1;

-- name: heavy_online_customer_example
select customerid, count(*), min(orderdate), max(orderdate), round(avg(subtotal),2), count(distinct creditcardid) from salesorderheader where onlineorderflag='t' group by 1 order by 2 desc limit 3;

-- name: salesperson_first_activity
select s.businessentityid, s.modifieddate sp_mod, (select min(ModifiedDate) from SalesPersonQuotaHistory q where q.BusinessEntityID=s.businessentityid) first_quota_set,
       (select min(QuotaDate) from SalesPersonQuotaHistory q where q.BusinessEntityID=s.businessentityid) first_quota,
       (select min(orderdate) from salesorderheader h where h.salespersonid=s.businessentityid) first_order,
       (select max(orderdate) from salesorderheader h where h.salespersonid=s.businessentityid) last_order,
       (select count(distinct territoryid) from salesorderheader h where h.salespersonid=s.businessentityid) n_terr,
       (select group_concat(distinct territoryid) from salesorderheader h where h.salespersonid=s.businessentityid) order_terrs,
       s.territoryid
from salesperson s order by 1;

-- name: quota_file_order
select count(*) pairs, sum(BusinessEntityID > pe or (BusinessEntityID = pe and QuotaDate > pd)) sorted_by_entity_date
from (select BusinessEntityID, QuotaDate, lag(BusinessEntityID) over (order by rowid) pe, lag(QuotaDate) over (order by rowid) pd from SalesPersonQuotaHistory) where pe is not null;

-- name: product_first_sale_vs_sellstart
select p.sellstartdate, count(*) products, min(fs), max(fs), sum(fs = p.sellstartdate) first_sale_on_start
from product p join (select productid, min(h.orderdate) fs from salesorderdetail d join salesorderheader h using(salesorderid) group by 1) x using(productid)
group by 1;

-- name: product_last_sale_vs_sellend
select p.sellenddate, count(*) products, min(ls), max(ls)
from product p join (select productid, max(h.orderdate) ls from salesorderdetail d join salesorderheader h using(salesorderid) group by 1) x using(productid)
group by 1;

-- name: orders_by_territory_channel
select territoryid, onlineorderflag, count(*) from salesorderheader group by 1,2 order by 1,2;

-- name: online_orders_on_reseller_days
select (select count(distinct orderdate) from salesorderheader where onlineorderflag='f') reseller_days;

-- name: reseller_line_dup_product
-- can one reseller order hold the same product twice (different special offers)?
select count(*) from (select salesorderid, productid from salesorderdetail group by 1,2 having count(*)>1);

-- name: description_modifieddate_vs_culture
select m.cultureid, d.modifieddate, count(*) from productdescription d join productmodelproductdescriptionculture m using(productdescriptionid) group by 1,2 order by 1,2;
