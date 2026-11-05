-- Northwind: source tables → events (refdata ingest). Money in cents, discount in percent.
-- customercustomerdemo and customerdemographics are empty and have no pack table.
-- Snapshots at N = 1998-05-06, the last orderdate and shippeddate (a rule).

-- entity: categories
SELECT CAST(categoryid AS TEXT) AS ext_id, categoryname, description, picture
FROM categories ORDER BY categoryid;

-- entity: suppliers
SELECT CAST(supplierid AS TEXT) AS ext_id, companyname FROM suppliers ORDER BY supplierid;

-- entity: products
SELECT CAST(productid AS TEXT) AS ext_id, productname, CAST(supplierid AS TEXT) AS supplier_id,
       CAST(categoryid AS TEXT) AS category_id, quantityperunit
FROM products ORDER BY productid;

-- entity: shippers
SELECT CAST(shipperid AS TEXT) AS ext_id, companyname FROM shippers ORDER BY shipperid;

-- entity: region
SELECT CAST(regionid AS TEXT) AS ext_id, regiondescription FROM region ORDER BY regionid;

-- entity: territories
SELECT territoryid AS ext_id, territorydescription, CAST(regionid AS TEXT) AS region_id
FROM territories ORDER BY territoryid;

-- entity: employees event=employee_hired
SELECT CAST(employeeid AS TEXT) AS ext_id, hiredate || ' 00:00:00' AS created_at, lastname,
       firstname, titleofcourtesy, birthdate
FROM employees ORDER BY employeeid;

-- entity: employeeterritories
SELECT employeeid || '/' || territoryid AS ext_id, CAST(employeeid AS TEXT) AS employee_id,
       territoryid AS territory_id
FROM employeeterritories ORDER BY employeeid, territoryid;

-- entity: customers
SELECT customerid AS ext_id,
       coalesce((SELECT MIN(orderdate) FROM orders o WHERE o.customerid = c.customerid),
                '1998-05-06') || ' 00:00:00' AS created_at,
       companyname
FROM customers c ORDER BY customerid;

-- entity: usstates
SELECT CAST(stateid AS TEXT) AS ext_id, statename, stateabbr, stateregion
FROM usstates ORDER BY stateid;

-- entity: customergroupthreshold
SELECT groupname AS ext_id, rangebottom, rangetop FROM customergroupthreshold ORDER BY groupname;

-- event: order_placed owner=customer_id ord=orderid
SELECT orderdate || ' 00:00:00' AS event_time, customerid AS customer_id, orderid,
       CAST(employeeid AS TEXT) AS employee_id,
       CAST(julianday(requireddate) - julianday(orderdate) AS INTEGER) AS required_lead_days,
       CAST(shipvia AS TEXT) AS ship_via, CAST(round(freight * 100) AS INTEGER) AS freight,
       shipname AS ship_name, shipaddress AS ship_address, shipcity AS ship_city,
       shipregion AS ship_region, shippostalcode AS ship_postal_code, shipcountry AS ship_country
FROM orders ORDER BY orderid;

-- event: order_line_added owner=customer_id ord=orderid
SELECT o.orderdate || ' 00:00:00' AS event_time, o.customerid AS customer_id, d.orderid,
       CAST(d.productid AS TEXT) AS product_id,
       CAST(round(d.unitprice * 100) AS INTEGER) AS unit_price, d.quantity,
       CAST(round(d.discount * 100) AS INTEGER) AS discount_pct
FROM order_details d JOIN orders o USING (orderid) ORDER BY d.orderid, d.productid;

-- event: order_shipped owner=customer_id ord=orderid
SELECT shippeddate || ' 00:00:00' AS event_time, customerid AS customer_id, orderid
FROM orders WHERE shippeddate IS NOT NULL ORDER BY orderid;

-- event: suppliers_snapshot owner=supplier_id
SELECT '1998-05-06 00:00:00' AS event_time, CAST(supplierid AS TEXT) AS supplier_id, contactname,
       contacttitle, address, city, region, postalcode, country, phone, fax, homepage
FROM suppliers ORDER BY supplierid;

-- event: products_snapshot owner=product_id
SELECT '1998-05-06 00:00:00' AS event_time, CAST(productid AS TEXT) AS product_id,
       CAST(round(unitprice * 100) AS INTEGER) AS unitprice, unitsinstock, unitsonorder,
       reorderlevel, discontinued
FROM products ORDER BY productid;

-- event: shippers_snapshot owner=shipper_id
SELECT '1998-05-06 00:00:00' AS event_time, CAST(shipperid AS TEXT) AS shipper_id, phone
FROM shippers ORDER BY shipperid;

-- event: employees_snapshot owner=employee_id
SELECT '1998-05-06 00:00:00' AS event_time, CAST(employeeid AS TEXT) AS employee_id, title,
       address, city, region, postalcode, country, homephone, extension, photo, notes,
       CAST(reportsto AS TEXT) AS reportsto, photopath
FROM employees ORDER BY employeeid;

-- event: customers_snapshot owner=customer_id
SELECT '1998-05-06 00:00:00' AS event_time, customerid AS customer_id, contactname, contacttitle,
       address, city, region, postalcode, country, phone, fax
FROM customers ORDER BY customerid;
