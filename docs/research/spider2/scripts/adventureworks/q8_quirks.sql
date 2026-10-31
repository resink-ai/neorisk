-- name: modifieddate_formats
-- text shapes of every DATE/TEXT time column (length and fractional-second digits)
select 'product.modifieddate' c, length(modifieddate) len, count(*) n, min(modifieddate), max(modifieddate) from product group by 2
union all select 'productdescription.modifieddate', length(modifieddate), count(*), min(modifieddate), max(modifieddate) from productdescription group by 2
union all select 'countryregioncurrency.modifieddate', length(modifieddate), count(*), min(modifieddate), max(modifieddate) from countryregioncurrency group by 2
union all select 'currencyrate.modifieddate', length(modifieddate), count(*), min(modifieddate), max(modifieddate) from currencyrate group by 2
union all select 'salesperson.modifieddate', length(modifieddate), count(*), min(modifieddate), max(modifieddate) from salesperson group by 2
union all select 'product.sellstartdate', length(sellstartdate), count(*), min(sellstartdate), max(sellstartdate) from product group by 2
union all select 'productreview.modifieddate', length(modifieddate), count(*), min(modifieddate), max(modifieddate) from productreview group by 2;

-- name: rowguid_shapes
select 'header' t, length(rowguid) len, sum(rowguid=lower(rowguid)) lower_n, count(*) from salesorderheader group by 2
union all select 'detail', length(rowguid), sum(rowguid=lower(rowguid)), count(*) from salesorderdetail group by 2
union all select 'product', length(rowguid), sum(rowguid=lower(rowguid)), count(*) from product group by 2
union all select 'quota', length(rowguid), sum(rowguid=upper(rowguid)), count(*) from SalesPersonQuotaHistory group by 2
union all select 'uuid v4 nibble in header', substr(rowguid,15,1), 0, count(*) from salesorderheader group by 2
union all select 'variant nibble in header', substr(rowguid,20,1), 0, count(*) from salesorderheader group by 2;

-- name: trailing_spaces
select 'product.' || c c, v, count(*) from (
  select 'sizeunitmeasurecode' c, sizeunitmeasurecode v from product union all select 'weightunitmeasurecode', weightunitmeasurecode from product
  union all select 'productline', productline from product union all select 'class', class from product union all select 'style', style from product)
group by 1,2 order by 1,2;

-- name: mixed_storage_classes
select 'product.weight' c, typeof(weight) t, count(*) from product group by 2
union all select 'product.productsubcategoryid', typeof(productsubcategoryid), count(*) from product group by 2
union all select 'header.salespersonid', typeof(salespersonid), count(*) from salesorderheader group by 2
union all select 'header.creditcardid', typeof(creditcardid), count(*) from salesorderheader group by 2
union all select 'header.currencyrateid', typeof(currencyrateid), count(*) from salesorderheader group by 2
union all select 'salesperson.territoryid', typeof(territoryid), count(*) from salesperson group by 2
union all select 'salesperson.salesquota', typeof(salesquota), count(*) from salesperson group by 2
union all select 'header.STATUS', typeof(STATUS), count(*) from salesorderheader group by 2;

-- name: newlines_in_text
select 'productreview.comments' c, sum(instr(comments, char(10))>0) lf, sum(instr(comments, char(13))>0) cr, count(*) from productreview
union all select 'productdescription.description', sum(instr(description, char(10))>0), sum(instr(description, char(13))>0), count(*) from productdescription
union all select 'productdescription non-ascii', sum(description glob '*[^ -~]*'), 0, count(*) from productdescription;

-- name: productdescription_duplicates
select description, count(*) n, group_concat(productdescriptionid) from productdescription group by 1 having count(*)>1 order by n desc limit 8;

-- name: product_dates
select sellstartdate, sellenddate, count(*), sum(finishedgoodsflag='t') fg from product group by 1,2 order by 1,2;

-- name: product_modifieddate
select modifieddate, count(*) from product group by 1;

-- name: product_sold_outside_sell_window
select count(*) lines,
       sum(h.orderdate < p.sellstartdate) before_start,
       sum(p.sellenddate<>'' and h.orderdate > p.sellenddate) after_end
from salesorderdetail d join salesorderheader h using(salesorderid) join product p using(productid);

-- name: unitprice_vs_listprice_by_channel
select h.onlineorderflag, sum(d.unitprice = p.listprice) eq_list, count(*) n
from salesorderdetail d join salesorderheader h using(salesorderid) join product p using(productid) group by 1;

-- name: online_price_history
-- online lines: distinct unit prices per product (list price changed over time?)
select np, count(*) products from (select d.productid, count(distinct d.unitprice) np from salesorderdetail d join salesorderheader h using(salesorderid) where h.onlineorderflag='t' group by 1) group by 1;

-- name: lines_with_zero_discount_special_offer
select specialofferid, unitpricediscount, count(*) from salesorderdetail where specialofferid>1 and unitpricediscount=0 group by 1,2;

-- name: productreview_columns
select productreviewid, modifeddate is null typo_col_null, modifieddate, reviewdate, modifieddate=reviewdate same from productreview;

-- name: reseller_orders_per_month
select strftime('%Y-%m', orderdate) m, count(*) orders, count(distinct orderdate) days, count(distinct customerid) customers from salesorderheader where onlineorderflag='f' group by 1 order by 1;

-- name: reseller_customers_order_once_per_month
select max(n) from (select customerid, strftime('%Y-%m', orderdate) m, count(*) n from salesorderheader where onlineorderflag='f' group by 1,2);

-- name: online_orders_per_day
select strftime('%Y', orderdate) y, count(*) orders, count(distinct orderdate) days, round(count(*)*1.0/count(distinct orderdate),2) per_day from salesorderheader where onlineorderflag='t' group by 1;

-- name: online_daily_gap_days
-- dates with no online order inside the range
select (julianday(max(orderdate))-julianday(min(orderdate))+1) - count(distinct orderdate) missing_days from salesorderheader where onlineorderflag='t';

-- name: comment_column
select comment, count(*) from salesorderheader group by 1;

-- name: territory_cost_cols
select sum(costytd=0 and costlastyear=0), count(*) from salesterritory;
