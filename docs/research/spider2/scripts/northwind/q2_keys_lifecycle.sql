-- name: fk_orphans
select 'orders.customerid->customers' fk, count(*) n, sum(c.customerid is null) orphans from orders o left join customers c using(customerid)
union all select 'orders.employeeid->employees', count(*), sum(e.employeeid is null) from orders o left join employees e using(employeeid)
union all select 'orders.shipvia->shippers', count(*), sum(s.shipperid is null) from orders o left join shippers s on s.shipperid=o.shipvia
union all select 'order_details.orderid->orders', count(*), sum(o.orderid is null) from order_details d left join orders o using(orderid)
union all select 'order_details.productid->products', count(*), sum(p.productid is null) from order_details d left join products p using(productid)
union all select 'products.supplierid->suppliers', count(*), sum(s.supplierid is null) from products p left join suppliers s using(supplierid)
union all select 'products.categoryid->categories', count(*), sum(c.categoryid is null) from products p left join categories c using(categoryid)
union all select 'employees.reportsto->employees', count(*), sum(e.employeeid is null) from employees x left join employees e on e.employeeid=x.reportsto where x.reportsto is not null
union all select 'employeeterritories.employeeid->employees', count(*), sum(e.employeeid is null) from employeeterritories et left join employees e using(employeeid)
union all select 'employeeterritories.territoryid->territories', count(*), sum(t.territoryid is null) from employeeterritories et left join territories t using(territoryid)
union all select 'territories.regionid->region', count(*), sum(r.regionid is null) from territories t left join region r using(regionid)
union all select 'customers.region->usstates.stateabbr (non-null)', count(*), sum(u.stateabbr is null) from customers c left join usstates u on u.stateabbr=c.region where c.region is not null and c.country='USA'
union all select 'suppliers.region->usstates.stateabbr (USA)', count(*), sum(u.stateabbr is null) from suppliers s left join usstates u on u.stateabbr=s.region where s.country='USA';
-- name: parents_without_children
select 'customers without orders' w, count(*) from customers c where not exists (select 1 from orders o where o.customerid=c.customerid)
union all select 'orders without lines', count(*) from orders o where not exists (select 1 from order_details d where d.orderid=o.orderid)
union all select 'products never ordered', count(*) from products p where not exists (select 1 from order_details d where d.productid=p.productid)
union all select 'shippers never used', count(*) from shippers s where not exists (select 1 from orders o where o.shipvia=s.shipperid)
union all select 'territories without employee', count(*) from territories t where not exists (select 1 from employeeterritories e where e.territoryid=t.territoryid)
union all select 'employees without orders', count(*) from employees e where not exists (select 1 from orders o where o.employeeid=e.employeeid)
union all select 'suppliers without products', count(*) from suppliers s where not exists (select 1 from products p where p.supplierid=s.supplierid);
-- name: customers_without_orders
select customerid, companyname, country from customers c where not exists (select 1 from orders o where o.customerid=c.customerid);
-- name: shipvia_use
select shipvia, count(*) n, round(avg(freight),2) avg_freight from orders group by 1;
-- name: date_ranges
select min(orderdate), max(orderdate), min(requireddate), max(requireddate), min(shippeddate), max(shippeddate) from orders;
-- name: id_vs_orderdate
select count(*) pairs, sum(orderdate >= p) nondecr, sum(orderdate = p) same_day from (select orderdate, lag(orderdate) over (order by orderid) p from orders) where p is not null;
-- name: required_minus_order
select cast(julianday(requireddate) - julianday(orderdate) as int) days, count(*) from orders group by 1 order by 2 desc;
-- name: shipped_minus_order
select cast(julianday(shippeddate) - julianday(orderdate) as int) days, count(*) from orders where shippeddate is not null group by 1 order by 1;
-- name: shipped_vs_required
select case when shippeddate is null then 'unshipped' when shippeddate < requireddate then 'early' when shippeddate = requireddate then 'on required date' else 'after required date' end k, count(*) from orders group by 1;
-- name: unshipped_orders
select orderid, orderdate, requireddate, shipvia, freight, employeeid from orders where shippeddate is null order by orderid;
-- name: last_dates
select (select max(orderdate) from orders) last_order, (select max(shippeddate) from orders) last_ship, (select min(orderdate) from orders where shippeddate is null) first_unshipped;
-- name: shipped_before_order
select count(*) from orders where shippeddate < orderdate;
-- name: weekdays
select 'orderdate' c, strftime('%w', orderdate) dow, count(*) from orders group by 2
union all select 'shippeddate', strftime('%w', shippeddate), count(*) from orders where shippeddate is not null group by 2
union all select 'requireddate', strftime('%w', requireddate), count(*) from orders group by 2;
-- name: orders_per_month
select substr(orderdate,1,7) m, count(*) n from orders group by 1 order by 1;
-- name: orders_per_day_dist
select k, count(*) days from (select orderdate, count(*) k from orders group by 1) group by 1;
-- name: business_days_gaps
select gap, count(*) from (select cast(julianday(orderdate) - julianday(lag(orderdate) over (order by orderid)) as int) gap from orders) where gap is not null group by 1 order by 1;
-- name: ship_address_vs_customer
select count(*) n, sum(o.shipname = c.companyname) name_eq, sum(o.shipaddress = c.address) addr_eq, sum(o.shipcity = c.city) city_eq,
  sum(o.shipregion is c.region) region_eq, sum(o.shippostalcode is c.postalcode) pc_eq, sum(o.shipcountry = c.country) country_eq,
  sum(o.shipname = c.companyname and o.shipaddress = c.address and o.shipcity = c.city and o.shipregion is c.region and o.shippostalcode is c.postalcode and o.shipcountry = c.country) all6
from orders o join customers c using(customerid);
-- name: ship_address_differences
select o.customerid, count(*) n, sum(o.shipname <> c.companyname) name_diff, sum(o.shipaddress <> c.address) addr_diff, min(o.shipname), min(c.companyname)
from orders o join customers c using(customerid)
where not (o.shipname = c.companyname and o.shipaddress = c.address and o.shipcity = c.city and o.shipregion is c.region and o.shippostalcode is c.postalcode and o.shipcountry = c.country)
group by 1;
-- name: ship_address_per_customer_constant
select count(*) customers, sum(k = 1) one_address from (select customerid, count(distinct shipname||'|'||shipaddress||'|'||shipcity||'|'||coalesce(shipregion,'~')||'|'||coalesce(shippostalcode,'~')||'|'||shipcountry) k from orders group by 1);
-- name: employee_territory_counts
select employeeid, count(*) from employeeterritories group by 1;
-- name: territories_by_region
select regionid, count(*) from territories group by 1;
-- name: orders_by_employee
select employeeid, count(*) n, sum(shippeddate >= requireddate) late_ge, sum(shippeddate > requireddate) late_gt from orders group by 1 order by 1;
