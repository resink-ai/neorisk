-- name: row_counts
select 'categories' t, count(*) n from categories union all select 'customercustomerdemo', count(*) from customercustomerdemo
union all select 'customerdemographics', count(*) from customerdemographics union all select 'customers', count(*) from customers
union all select 'employees', count(*) from employees union all select 'employeeterritories', count(*) from employeeterritories
union all select 'order_details', count(*) from order_details union all select 'orders', count(*) from orders
union all select 'products', count(*) from products union all select 'region', count(*) from region
union all select 'shippers', count(*) from shippers union all select 'suppliers', count(*) from suppliers
union all select 'territories', count(*) from territories union all select 'usstates', count(*) from usstates
union all select 'customergroupthreshold', count(*) from customergroupthreshold;
-- name: sqlite_master
select type, name from sqlite_master;
-- name: key_uniqueness
select 'categories.categoryid' k, count(*) n, count(distinct categoryid) d from categories
union all select 'customers.customerid', count(*), count(distinct customerid) from customers
union all select 'employees.employeeid', count(*), count(distinct employeeid) from employees
union all select 'employeeterritories(e,t)', count(*), count(distinct employeeid||'|'||territoryid) from employeeterritories
union all select 'employeeterritories.territoryid', count(*), count(distinct territoryid) from employeeterritories
union all select 'order_details(o,p)', count(*), count(distinct orderid||'|'||productid) from order_details
union all select 'orders.orderid', count(*), count(distinct orderid) from orders
union all select 'products.productid', count(*), count(distinct productid) from products
union all select 'region.regionid', count(*), count(distinct regionid) from region
union all select 'shippers.shipperid', count(*), count(distinct shipperid) from shippers
union all select 'suppliers.supplierid', count(*), count(distinct supplierid) from suppliers
union all select 'territories.territoryid', count(*), count(distinct territoryid) from territories
union all select 'usstates.stateid', count(*), count(distinct stateid) from usstates
union all select 'usstates.stateabbr', count(*), count(distinct stateabbr) from usstates
union all select 'customergroupthreshold.groupname', count(*), count(distinct groupname) from customergroupthreshold;
-- name: id_ranges
select 'orders' t, min(orderid), max(orderid), count(*) from orders union all select 'products', min(productid), max(productid), count(*) from products
union all select 'employees', min(employeeid), max(employeeid), count(*) from employees union all select 'suppliers', min(supplierid), max(supplierid), count(*) from suppliers
union all select 'shippers', min(shipperid), max(shipperid), count(*) from shippers union all select 'usstates', min(stateid), max(stateid), count(*) from usstates;
-- name: rowid_order
select 'orders by orderid' t, count(*) pairs, sum(orderid > p) incr from (select orderid, lag(orderid) over (order by rowid) p from orders) where p is not null
union all select 'order_details by (o,p)', count(*), sum(k > p) from (select orderid*1000+productid k, lag(orderid*1000+productid) over (order by rowid) p from order_details) where p is not null
union all select 'customers by id', count(*), sum(customerid > p) from (select customerid, lag(customerid) over (order by rowid) p from customers) where p is not null
union all select 'territories by id', count(*), sum(territoryid > p) from (select territoryid, lag(territoryid) over (order by rowid) p from territories) where p is not null;
-- name: typeof_columns
select 'orders.orderdate' c, typeof(orderdate) t, count(*) from orders group by 2
union all select 'orders.requireddate', typeof(requireddate), count(*) from orders group by 2
union all select 'orders.shippeddate', typeof(shippeddate), count(*) from orders group by 2
union all select 'orders.freight', typeof(freight), count(*) from orders group by 2
union all select 'orders.shipvia', typeof(shipvia), count(*) from orders group by 2
union all select 'orders.employeeid', typeof(employeeid), count(*) from orders group by 2
union all select 'orders.shipregion', typeof(shipregion), count(*) from orders group by 2
union all select 'orders.shippostalcode', typeof(shippostalcode), count(*) from orders group by 2
union all select 'order_details.unitprice', typeof(unitprice), count(*) from order_details group by 2
union all select 'order_details.discount', typeof(discount), count(*) from order_details group by 2
union all select 'order_details.quantity', typeof(quantity), count(*) from order_details group by 2
union all select 'products.unitprice', typeof(unitprice), count(*) from products group by 2
union all select 'categories.picture', typeof(picture), count(*) from categories group by 2
union all select 'employees.photo', typeof(photo), count(*) from employees group by 2
union all select 'employees.birthdate', typeof(birthdate), count(*) from employees group by 2
union all select 'employees.reportsto', typeof(reportsto), count(*) from employees group by 2
union all select 'customergroupthreshold.rangebottom', typeof(rangebottom), count(*) from customergroupthreshold group by 2
union all select 'customergroupthreshold.rangetop', typeof(rangetop), count(*) from customergroupthreshold group by 2
union all select 'territories.territoryid', typeof(territoryid), count(*) from territories group by 2;
-- name: date_formats
select 'orderdate' c, length(orderdate) len, count(*) from orders group by 2
union all select 'requireddate', length(requireddate), count(*) from orders group by 2
union all select 'shippeddate', length(shippeddate), count(*) from orders group by 2
union all select 'birthdate', length(birthdate), count(*) from employees group by 2
union all select 'hiredate', length(hiredate), count(*) from employees group by 2;
-- name: null_vs_empty
select 'orders.shipregion' c, sum(shipregion is null) nulls, sum(shipregion='') empties from orders
union all select 'orders.shippostalcode', sum(shippostalcode is null), sum(shippostalcode='') from orders
union all select 'orders.shippeddate', sum(shippeddate is null), sum(shippeddate='') from orders
union all select 'orders.customerid', sum(customerid is null), sum(customerid='') from orders
union all select 'customers.region', sum(region is null), sum(region='') from customers
union all select 'customers.fax', sum(fax is null), sum(fax='') from customers
union all select 'customers.postalcode', sum(postalcode is null), sum(postalcode='') from customers
union all select 'suppliers.region', sum(region is null), sum(region='') from suppliers
union all select 'suppliers.fax', sum(fax is null), sum(fax='') from suppliers
union all select 'suppliers.homepage', sum(homepage is null), sum(homepage='') from suppliers
union all select 'employees.region', sum(region is null), sum(region='') from employees
union all select 'employees.reportsto', sum(reportsto is null), 0 from employees
union all select 'usstates.stateregion', sum(stateregion is null), sum(stateregion='') from usstates
union all select 'categories.description', sum(description is null), sum(description='') from categories;
-- name: blobs
select 'categories.picture' c, length(picture) len, hex(picture) h, count(*) from categories group by 2,3
union all select 'employees.photo', length(photo), hex(photo), count(*) from employees group by 2,3;
-- name: whitespace
select 'territories.territorydescription' c, sum(territorydescription <> rtrim(territorydescription)) trailing, max(length(territorydescription)) maxlen from territories
union all select 'region.regiondescription', sum(regiondescription <> rtrim(regiondescription)), max(length(regiondescription)) from region
union all select 'employees.notes', sum(notes <> rtrim(notes)), max(length(notes)) from employees
union all select 'customers.*', sum(companyname<>trim(companyname) or coalesce(address,'')<>trim(coalesce(address,''))), 0 from customers
union all select 'orders.ship*', sum(shipname<>trim(shipname) or shipaddress<>trim(shipaddress)), 0 from orders;
-- name: territory_desc_truncation
select territoryid, '[' || territorydescription || ']' d, length(territorydescription) from territories where length(territorydescription) >= 9 order by 3 desc limit 12;
-- name: region_desc
select regionid, '[' || regiondescription || ']', length(regiondescription) from region;
-- name: photopath_typo
select photopath, count(*) from employees group by 1;
