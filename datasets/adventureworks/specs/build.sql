-- AdventureWorks: events → source tables (refdata rebuild, DuckDB).

-- table: productcategory
SELECT CAST(c.ext_id AS BIGINT) AS productcategoryid, c.name, c.rowguid, x.modifieddate
FROM product_categories c LEFT JOIN product_categories_snapshot x USING (product_category_id);

-- table: productsubcategory
SELECT CAST(s.ext_id AS BIGINT) AS productsubcategoryid, CAST(c.ext_id AS BIGINT) AS productcategoryid,
       s.name, s.rowguid, x.modifieddate
FROM product_subcategories s JOIN product_categories c USING (product_category_id)
LEFT JOIN product_subcategories_snapshot x USING (product_subcategory_id);

-- table: product
SELECT CAST(p.ext_id AS BIGINT) AS productid, p.name AS NAME, p.productnumber, x.makeflag,
       p.finishedgoodsflag, p.color, x.safetystocklevel, x.reorderpoint, x.standardcost,
       x.listprice, p.size, p.sizeunitmeasurecode, p.weightunitmeasurecode, p.weight,
       x.daystomanufacture, p.productline, p.class, p.style, p.productsubcategoryid,
       p.productmodelid, p.sellstartdate, x.sellenddate, x.discontinueddate, p.rowguid,
       x.modifieddate
FROM products p LEFT JOIN products_snapshot x USING (product_id);

-- table: productdescription
SELECT CAST(d.ext_id AS BIGINT) AS productdescriptionid, d.description, d.rowguid, x.modifieddate
FROM product_descriptions d LEFT JOIN product_descriptions_snapshot x USING (product_description_id);

-- table: productmodelproductdescriptionculture
SELECT d.productmodelid, CAST(d.ext_id AS BIGINT) AS productdescriptionid, d.cultureid,
       x.link_modifieddate AS modifieddate
FROM product_descriptions d LEFT JOIN product_descriptions_snapshot x USING (product_description_id);

-- table: salesterritory
SELECT CAST(t.ext_id AS BIGINT) AS territoryid, t.name, t.countryregioncode, t."group",
       x.salesytd, x.saleslastyear, x.costytd, x.costlastyear, t.rowguid, x.modifieddate
FROM territories t LEFT JOIN territories_snapshot x USING (territory_id);

-- table: salesperson
SELECT CAST(s.ext_id AS BIGINT) AS businessentityid, x.territoryid, x.salesquota, x.bonus,
       x.commissionpct, x.salesytd, x.saleslastyear, s.rowguid, x.modifieddate
FROM salespersons s LEFT JOIN salespersons_snapshot x USING (salesperson_id);

-- table: countryregioncurrency
SELECT c.countryregioncode, c.currencycode, x.modifieddate
FROM country_currencies c LEFT JOIN country_currencies_snapshot x USING (country_currency_id);

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
