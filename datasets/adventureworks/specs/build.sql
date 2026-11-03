-- AdventureWorks: events → source tables (refdata rebuild, DuckDB).

-- table: productcategory
SELECT CAST(ext_id AS BIGINT) AS productcategoryid, name, rowguid, modifieddate
FROM product_categories;

-- table: productsubcategory
SELECT CAST(s.ext_id AS BIGINT) AS productsubcategoryid, CAST(c.ext_id AS BIGINT) AS productcategoryid,
       s.name, s.rowguid, s.modifieddate
FROM product_subcategories s JOIN product_categories c USING (product_category_id);

-- table: product
SELECT CAST(ext_id AS BIGINT) AS productid, name AS NAME, productnumber, makeflag,
       finishedgoodsflag, color, safetystocklevel, reorderpoint, standardcost, listprice, size,
       sizeunitmeasurecode, weightunitmeasurecode, weight, daystomanufacture, productline,
       class, style, productsubcategoryid, productmodelid, sellstartdate, sellenddate,
       discontinueddate, rowguid, modifieddate
FROM products;

-- table: productdescription
SELECT CAST(ext_id AS BIGINT) AS productdescriptionid, description, rowguid, modifieddate
FROM product_descriptions;

-- table: productmodelproductdescriptionculture
SELECT productmodelid, CAST(ext_id AS BIGINT) AS productdescriptionid, cultureid,
       link_modifieddate AS modifieddate
FROM product_descriptions;

-- table: salesterritory
SELECT CAST(ext_id AS BIGINT) AS territoryid, name, countryregioncode, "group", salesytd,
       saleslastyear, costytd, costlastyear, rowguid, modifieddate
FROM territories;

-- table: salesperson
SELECT CAST(ext_id AS BIGINT) AS businessentityid, territoryid, salesquota, bonus,
       commissionpct, salesytd, saleslastyear, rowguid, modifieddate
FROM salespersons;

-- table: countryregioncurrency
SELECT countryregioncode, currencycode, modifieddate FROM country_currencies;

-- table: salesorderheader
-- subtotal = the line sum rounded half-up to 1e-4; totaldue adds integers and divides once.
WITH sub AS (
  SELECT salesorderid, (sum(unitprice_e4 * orderqty * (100 - discount_pct)) + 50) // 100 AS sub_e4
  FROM order_line_added GROUP BY salesorderid)
SELECT o.salesorderid, o.revisionnumber,
       strftime(o.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS orderdate, o.duedate,
       strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS shipdate,
       CASE WHEN s.salesorderid IS NOT NULL THEN '5' END AS STATUS, o.onlineorderflag,
       o.purchaseordernumber, o.accountnumber, o.customerid, o.salespersonid,
       CAST(t.ext_id AS BIGINT) AS territoryid, o.billtoaddressid, o.shiptoaddressid,
       o.shipmethodid, o.creditcardid, o.creditcardapprovalcode, o.currencyrateid,
       b.sub_e4 / 10000.0 AS subtotal, o.taxamt_e4 / 10000.0 AS taxamt,
       o.freight_e4 / 10000.0 AS freight,
       (b.sub_e4 + o.taxamt_e4 + o.freight_e4) / 10000.0 AS totaldue, o.comment, o.rowguid,
       strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS modifieddate
FROM order_placed o JOIN territories t USING (territory_id) JOIN sub b USING (salesorderid)
LEFT JOIN order_shipped s USING (salesorderid);

-- table: salesorderdetail
SELECT l.salesorderid, l.salesorderdetailid, l.carriertrackingnumber, l.orderqty,
       CAST(p.ext_id AS BIGINT) AS productid, l.specialofferid,
       l.unitprice_e4 / 10000.0 AS unitprice, l.discount_pct / 100.0 AS unitpricediscount,
       l.rowguid, strftime(l.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS modifieddate
FROM order_line_added l JOIN products p USING (product_id);

-- table: currencyrate
SELECT currencyrateid, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS currencyratedate,
       fromcurrencycode, tocurrencycode, averagerate, endofdayrate, modifieddate
FROM currency_rate_published;

-- table: SalesPersonQuotaHistory
SELECT CAST(s.ext_id AS BIGINT) AS BusinessEntityID, q.quotadate AS QuotaDate,
       q.salesquota AS SalesQuota, q.rowguid,
       strftime(q.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS ModifiedDate
FROM quota_set q JOIN salespersons s USING (salesperson_id);

-- table: productreview
SELECT r.productreviewid, CAST(p.ext_id AS BIGINT) AS productid, r.reviewername,
       strftime(r.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS reviewdate,
       r.emailaddress, r.rating, r.comments, NULL::VARCHAR AS modifeddate,
       strftime(r.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS modifieddate
FROM product_reviewed r JOIN products p USING (product_id);
