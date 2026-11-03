-- Northwind: events → source tables (refdata rebuild, DuckDB).
-- float4 money: CAST(printf('%.9g', CAST(cents / 100.0 AS FLOAT)) AS DOUBLE) is the stored value.

-- table: categories
SELECT CAST(ext_id AS BIGINT) AS categoryid, categoryname, description, picture FROM categories;

-- table: customercustomerdemo
SELECT NULL::VARCHAR AS customerid, NULL::VARCHAR AS customertypeid WHERE false;

-- table: customerdemographics
SELECT NULL::VARCHAR AS customertypeid, NULL::VARCHAR AS customerdesc WHERE false;

-- table: customers
SELECT ext_id AS customerid, companyname, contactname, contacttitle, address, city, region,
       postalcode, country, phone, fax
FROM customers;

-- table: employees
SELECT CAST(e.ext_id AS BIGINT) AS employeeid, e.lastname, e.firstname, e.title,
       e.titleofcourtesy, e.birthdate,
       strftime(e.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS hiredate, e.address, e.city,
       e.region, e.postalcode, e.country, e.homephone, e.extension, e.photo, e.notes,
       CAST(b.ext_id AS BIGINT) AS reportsto, e.photopath
FROM employees e LEFT JOIN employees b ON b.employee_id = e.reportsto;

-- table: employeeterritories
SELECT CAST(e.ext_id AS BIGINT) AS employeeid, t.ext_id AS territoryid
FROM employeeterritories x JOIN employees e USING (employee_id) JOIN territories t USING (territory_id);

-- table: order_details
SELECT l.orderid, CAST(p.ext_id AS BIGINT) AS productid,
       CAST(printf('%.9g', CAST(l.unit_price / 100.0 AS FLOAT)) AS DOUBLE) AS unitprice,
       l.quantity,
       CAST(printf('%.9g', CAST(l.discount_pct / 100.0 AS FLOAT)) AS DOUBLE) AS discount
FROM order_line_added l JOIN products p USING (product_id);

-- table: orders
SELECT o.orderid, c.ext_id AS customerid, CAST(e.ext_id AS BIGINT) AS employeeid,
       strftime(o.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS orderdate,
       strftime((o.event_time + o.required_lead_days * INTERVAL 1 DAY) AT TIME ZONE 'UTC',
                '%Y-%m-%d') AS requireddate,
       strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS shippeddate,
       CAST(v.ext_id AS BIGINT) AS shipvia,
       CAST(printf('%.9g', CAST(o.freight / 100.0 AS FLOAT)) AS DOUBLE) AS freight,
       o.ship_name AS shipname, o.ship_address AS shipaddress, o.ship_city AS shipcity,
       o.ship_region AS shipregion, o.ship_postal_code AS shippostalcode,
       o.ship_country AS shipcountry
FROM order_placed o JOIN customers c USING (customer_id) JOIN employees e USING (employee_id)
JOIN shippers v ON v.shipper_id = o.ship_via LEFT JOIN order_shipped s USING (orderid);

-- table: products
SELECT CAST(p.ext_id AS BIGINT) AS productid, p.productname, CAST(s.ext_id AS BIGINT) AS supplierid,
       CAST(c.ext_id AS BIGINT) AS categoryid, p.quantityperunit,
       CAST(printf('%.9g', CAST(p.unitprice / 100.0 AS FLOAT)) AS DOUBLE) AS unitprice,
       p.unitsinstock, p.unitsonorder, p.reorderlevel, p.discontinued
FROM products p JOIN suppliers s USING (supplier_id) JOIN categories c USING (category_id);

-- table: region
SELECT CAST(ext_id AS BIGINT) AS regionid, regiondescription FROM region;

-- table: shippers
SELECT CAST(ext_id AS BIGINT) AS shipperid, companyname, phone FROM shippers;

-- table: suppliers
SELECT CAST(ext_id AS BIGINT) AS supplierid, companyname, contactname, contacttitle, address, city,
       region, postalcode, country, phone, fax, homepage
FROM suppliers;

-- table: territories
SELECT t.ext_id AS territoryid, t.territorydescription, CAST(r.ext_id AS BIGINT) AS regionid
FROM territories t JOIN region r USING (region_id);

-- table: usstates
SELECT CAST(ext_id AS BIGINT) AS stateid, statename, stateabbr, stateregion FROM usstates;

-- table: customergroupthreshold
SELECT ext_id AS groupname, rangebottom, rangetop FROM customergroupthreshold;
