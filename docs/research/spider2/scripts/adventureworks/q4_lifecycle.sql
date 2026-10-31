-- name: time_of_day
select 'orderdate' c, substr(orderdate,11) tod, count(*) from salesorderheader group by 2
union all select 'duedate', substr(duedate,11), count(*) from salesorderheader group by 2
union all select 'shipdate', substr(shipdate,11), count(*) from salesorderheader group by 2
union all select 'header.modifieddate', substr(modifieddate,11), count(*) from salesorderheader group by 2
union all select 'detail.modifieddate', substr(modifieddate,11), count(*) from salesorderdetail group by 2
union all select 'currencyratedate', substr(currencyratedate,11), count(*) from currencyrate group by 2;

-- name: lead_times_by_channel
select onlineorderflag, julianday(duedate)-julianday(orderdate) due_d, julianday(shipdate)-julianday(orderdate) ship_d, count(*)
from salesorderheader group by 1,2,3 order by 1,2,3;

-- name: status_revision
select status, revisionnumber, onlineorderflag, count(*) from salesorderheader group by 1,2,3;

-- name: revision9_orders
select min(orderdate), max(orderdate), count(*), group_concat(salesorderid) from salesorderheader where revisionnumber=9;

-- name: header_modifieddate_vs_shipdate
select sum(modifieddate=shipdate) eq_ship, sum(modifieddate=orderdate) eq_order, count(*) n from salesorderheader;

-- name: detail_modifieddate_vs_header
select sum(d.modifieddate=h.orderdate) eq_orderdate, sum(d.modifieddate=h.shipdate) eq_ship, count(*) n
from salesorderdetail d join salesorderheader h using(salesorderid);

-- name: snapshot_bounds
select max(orderdate) last_order, max(shipdate) last_ship, max(duedate) last_due, max(modifieddate) last_mod,
       sum(shipdate > (select max(orderdate) from salesorderheader)) shipped_after_last_order,
       (select max(currencyratedate) from currencyrate) last_rate,
       (select max(QuotaDate) from SalesPersonQuotaHistory) last_quota,
       (select max(modifieddate) from salesperson) last_sp_mod
from salesorderheader;

-- name: shipmethod_by_channel
select onlineorderflag, shipmethodid, count(*) from salesorderheader group by 1,2;

-- name: channel_columns
-- which columns are empty by channel
select onlineorderflag, count(*) n, sum(salespersonid='') no_sp, sum(purchaseordernumber='') no_po,
       sum(creditcardid='') no_cc, sum(currencyrateid='') no_rate, sum(billtoaddressid<>shiptoaddressid) bill_ne_ship
from salesorderheader group by 1;

-- name: carriertracking_by_channel
select h.onlineorderflag, count(*) lines, sum(d.carriertrackingnumber='') empty_ctn,
       count(distinct d.carriertrackingnumber) distinct_ctn
from salesorderdetail d join salesorderheader h using(salesorderid) group by 1;

-- name: carriertracking_one_per_order
select count(*) offline_orders, sum(nctn=1) one_ctn, (select count(distinct carriertrackingnumber) from salesorderdetail where carriertrackingnumber<>'') distinct_ctn_total
from (select salesorderid, count(distinct carriertrackingnumber) nctn from salesorderdetail d join salesorderheader h using(salesorderid) where h.onlineorderflag='f' group by 1);

-- name: accountnumber_format
select sum(accountnumber = '10-4020-' || printf('%06d', customerid)) a4020_custid,
       sum(accountnumber like '10-4020-%') like4020, sum(accountnumber like '10-4030-%') like4030,
       sum(accountnumber like '10-4030-%' and onlineorderflag='t') like4030_online,
       sum(accountnumber like '10-4020-%' and onlineorderflag='f') like4020_offline,
       sum(accountnumber = '10-4030-' || printf('%06d', customerid)) a4030_custid,
       count(*) n from salesorderheader;

-- name: accountnumber_vs_customer_ids
select onlineorderflag, min(customerid), max(customerid), min(cast(substr(accountnumber,9) as int)), max(cast(substr(accountnumber,9) as int)) from salesorderheader group by 1;

-- name: approvalcode_format
select substr(creditcardapprovalcode, instr(creditcardapprovalcode,'Vi'), 2) mid, length(creditcardapprovalcode) len, count(*)
from salesorderheader where creditcardapprovalcode<>'' group by 1,2 order by 3 desc limit 10;

-- name: po_format
select length(purchaseordernumber) len, count(*) from salesorderheader where purchaseordernumber<>'' group by 1;

-- name: rate_vs_order
select count(*) with_rate,
       sum(c.currencyratedate = h.orderdate) rate_date_eq_orderdate,
       sum(exists(select 1 from countryregioncurrency x where x.countryregioncode = t.countryregioncode and x.currencycode = c.tocurrencycode)) currency_matches_territory_country
from salesorderheader h join currencyrate c on c.currencyrateid = h.currencyrateid join salesterritory t on t.territoryid = h.territoryid;

-- name: rate_presence_by_territory
select t.name, t.countryregioncode, h.onlineorderflag, count(*) n, sum(h.currencyrateid<>'') with_rate,
       group_concat(distinct c.tocurrencycode) currencies
from salesorderheader h join salesterritory t using(territoryid) left join currencyrate c on c.currencyrateid=h.currencyrateid
group by 1,2,3 order by 1,3;

-- name: rate_rule_check
-- an order has a rate iff its territory is outside the US; is the rate id = the (orderdate, currency) row?
select count(*) n,
       sum((h.currencyrateid<>'') = (t.countryregioncode<>'US')) rate_iff_non_us
from salesorderheader h join salesterritory t using(territoryid);

-- name: creditcard_reuse
select count(*) cards, sum(n>1) reused, max(n) from (select creditcardid, count(*) n, count(distinct customerid) nc from salesorderheader where creditcardid<>'' group by 1);
-- name: creditcard_shared_by_customers
select count(*) from (select creditcardid from salesorderheader where creditcardid<>'' group by 1 having count(distinct customerid)>1);
-- name: approvalcode_unique
select count(*), count(distinct creditcardapprovalcode) from salesorderheader where creditcardapprovalcode<>'';
