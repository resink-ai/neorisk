-- AdventureWorks: source tables → events (refdata ingest). Money in 1e-4 units; mixed
-- number-or-'' columns as text.

-- entity: product_categories
SELECT CAST(productcategoryid AS TEXT) AS ext_id, name, rowguid, modifieddate
FROM productcategory ORDER BY productcategoryid;

-- entity: product_subcategories
SELECT CAST(productsubcategoryid AS TEXT) AS ext_id,
       CAST(productcategoryid AS TEXT) AS product_category_id, name, rowguid, modifieddate
FROM productsubcategory ORDER BY productsubcategoryid;

-- entity: products
SELECT CAST(productid AS TEXT) AS ext_id, NAME AS name, productnumber, makeflag,
       finishedgoodsflag, color, safetystocklevel, reorderpoint, standardcost, listprice, size,
       sizeunitmeasurecode, weightunitmeasurecode, CAST(weight AS TEXT) AS weight,
       daystomanufacture, productline, class, style,
       CAST(productsubcategoryid AS TEXT) AS productsubcategoryid,
       CAST(productmodelid AS TEXT) AS productmodelid, sellstartdate, sellenddate,
       discontinueddate, rowguid, modifieddate
FROM product ORDER BY productid;

-- entity: product_descriptions
SELECT CAST(d.productdescriptionid AS TEXT) AS ext_id, d.description, d.rowguid, d.modifieddate,
       l.productmodelid, l.cultureid, l.modifieddate AS link_modifieddate
FROM productdescription d JOIN productmodelproductdescriptionculture l USING (productdescriptionid)
ORDER BY d.productdescriptionid;

-- entity: territories
SELECT CAST(territoryid AS TEXT) AS ext_id, name, countryregioncode, "group", salesytd,
       saleslastyear, costytd, costlastyear, rowguid, modifieddate
FROM salesterritory ORDER BY territoryid;

-- entity: salespersons
SELECT CAST(businessentityid AS TEXT) AS ext_id, CAST(territoryid AS TEXT) AS territoryid,
       CAST(salesquota AS TEXT) AS salesquota, bonus, commissionpct, salesytd, saleslastyear,
       rowguid, modifieddate
FROM salesperson ORDER BY businessentityid;

-- entity: country_currencies
SELECT countryregioncode || '/' || currencycode AS ext_id, countryregioncode, currencycode,
       modifieddate
FROM countryregioncurrency ORDER BY countryregioncode, currencycode;

-- event: order_placed owner=salesorderid
SELECT orderdate AS event_time, salesorderid, revisionnumber, duedate, onlineorderflag,
       purchaseordernumber, accountnumber, customerid, CAST(salespersonid AS TEXT) AS salespersonid,
       CAST(territoryid AS TEXT) AS territory_id, billtoaddressid, shiptoaddressid, shipmethodid,
       CAST(creditcardid AS TEXT) AS creditcardid, creditcardapprovalcode,
       CAST(currencyrateid AS TEXT) AS currencyrateid,
       CAST(round(taxamt * 10000) AS INTEGER) AS taxamt_e4,
       CAST(round(freight * 10000) AS INTEGER) AS freight_e4, comment, rowguid
FROM salesorderheader ORDER BY salesorderid;

-- event: order_line_added owner=salesorderid ord=salesorderdetailid
SELECT h.orderdate AS event_time, d.salesorderid, d.salesorderdetailid, d.carriertrackingnumber,
       d.orderqty, CAST(d.productid AS TEXT) AS product_id, d.specialofferid,
       CAST(round(d.unitprice * 10000) AS INTEGER) AS unitprice_e4,
       CAST(round(d.unitpricediscount * 100) AS INTEGER) AS discount_pct, d.rowguid
FROM salesorderdetail d JOIN salesorderheader h USING (salesorderid)
ORDER BY d.salesorderdetailid;

-- event: order_shipped owner=salesorderid
SELECT shipdate AS event_time, salesorderid FROM salesorderheader ORDER BY salesorderid;

-- event: currency_rate_published owner=tocurrencycode
SELECT currencyratedate AS event_time, tocurrencycode, currencyrateid, fromcurrencycode,
       averagerate, endofdayrate, modifieddate
FROM currencyrate ORDER BY currencyrateid;

-- event: quota_set owner=salesperson_id
SELECT ModifiedDate AS event_time, CAST(BusinessEntityID AS TEXT) AS salesperson_id,
       QuotaDate AS quotadate, SalesQuota AS salesquota, rowguid
FROM SalesPersonQuotaHistory ORDER BY BusinessEntityID, QuotaDate;

-- event: product_reviewed owner=product_id
SELECT reviewdate AS event_time, CAST(productid AS TEXT) AS product_id, productreviewid,
       reviewername, emailaddress, rating, comments
FROM productreview ORDER BY productreviewid;
