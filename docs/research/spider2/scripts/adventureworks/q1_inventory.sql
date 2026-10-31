-- name: pk_uniqueness
select 'salesorderheader(salesorderid)' k, count(*) n, count(distinct salesorderid) d from salesorderheader
union all select 'salesorderdetail(salesorderdetailid)', count(*), count(distinct salesorderdetailid) from salesorderdetail
union all select 'salesorderdetail(salesorderid,productid,specialofferid)', count(*), count(distinct salesorderid||'/'||productid||'/'||specialofferid) from salesorderdetail
union all select 'salesorderdetail(salesorderid,productid)', count(*), count(distinct salesorderid||'/'||productid) from salesorderdetail
union all select 'product(productid)', count(*), count(distinct productid) from product
union all select 'product(name)', count(*), count(distinct name) from product
union all select 'product(productnumber)', count(*), count(distinct productnumber) from product
union all select 'productcategory', count(*), count(distinct productcategoryid) from productcategory
union all select 'productsubcategory', count(*), count(distinct productsubcategoryid) from productsubcategory
union all select 'productdescription', count(*), count(distinct productdescriptionid) from productdescription
union all select 'pmpdc(model,culture)', count(*), count(distinct productmodelid||'/'||cultureid) from productmodelproductdescriptionculture
union all select 'pmpdc(descriptionid)', count(*), count(distinct productdescriptionid) from productmodelproductdescriptionculture
union all select 'productreview', count(*), count(distinct productreviewid) from productreview
union all select 'salesperson', count(*), count(distinct businessentityid) from salesperson
union all select 'salesterritory', count(*), count(distinct territoryid) from salesterritory
union all select 'countryregioncurrency(country,currency)', count(*), count(distinct countryregioncode||'/'||currencycode) from countryregioncurrency
union all select 'currencyrate(id)', count(*), count(distinct currencyrateid) from currencyrate
union all select 'currencyrate(date,from,to)', count(*), count(distinct currencyratedate||fromcurrencycode||tocurrencycode) from currencyrate
union all select 'quota(entity,date)', count(*), count(distinct BusinessEntityID||'/'||QuotaDate) from SalesPersonQuotaHistory
union all select 'all rowguids (lower, no braces) across 9 tables', count(*), count(distinct g) from (
  select rowguid g from salesorderheader union all select rowguid from salesorderdetail union all select rowguid from product
  union all select rowguid from productcategory union all select rowguid from productsubcategory union all select rowguid from productdescription
  union all select rowguid from salesperson union all select rowguid from salesterritory
  union all select lower(substr(rowguid,2,36)) from SalesPersonQuotaHistory);

-- name: fk_coverage
select 'detail.salesorderid -> header' fk, count(*) n, sum(h.salesorderid is not null) ok from salesorderdetail d left join salesorderheader h using(salesorderid)
union all select 'header with >=1 detail', count(*), sum(exists(select 1 from salesorderdetail d where d.salesorderid=h.salesorderid)) from salesorderheader h
union all select 'detail.productid -> product', count(*), sum(p.productid is not null) from salesorderdetail d left join product p using(productid)
union all select 'product sold at least once', count(*), sum(exists(select 1 from salesorderdetail d where d.productid=p.productid)) from product p
union all select 'finished goods sold at least once', count(*), sum(exists(select 1 from salesorderdetail d where d.productid=p.productid)) from product p where finishedgoodsflag='t'
union all select 'header.salespersonid (non-empty) -> salesperson', count(*), sum(s.businessentityid is not null) from salesorderheader h left join salesperson s on s.businessentityid=h.salespersonid where h.salespersonid<>''
union all select 'salesperson with >=1 order', count(*), sum(exists(select 1 from salesorderheader h where h.salespersonid=s.businessentityid)) from salesperson s
union all select 'header.territoryid -> territory', count(*), sum(t.territoryid is not null) from salesorderheader h left join salesterritory t using(territoryid)
union all select 'header.currencyrateid (non-empty) -> currencyrate', count(*), sum(c.currencyrateid is not null) from salesorderheader h left join currencyrate c on c.currencyrateid=h.currencyrateid where h.currencyrateid<>''
union all select 'salesperson.territoryid (non-empty) -> territory', count(*), sum(t.territoryid is not null) from salesperson s left join salesterritory t on t.territoryid=s.territoryid where s.territoryid<>''
union all select 'product.subcategory (non-empty) -> productsubcategory', count(*), sum(sc.productsubcategoryid is not null) from product p left join productsubcategory sc on sc.productsubcategoryid=p.productsubcategoryid where p.productsubcategoryid<>''
union all select 'subcategory -> category', count(*), sum(c.productcategoryid is not null) from productsubcategory s left join productcategory c using(productcategoryid)
union all select 'pmpdc.descriptionid -> productdescription', count(*), sum(pd.productdescriptionid is not null) from productmodelproductdescriptionculture m left join productdescription pd using(productdescriptionid)
union all select 'productdescription used by pmpdc', count(*), sum(exists(select 1 from productmodelproductdescriptionculture m where m.productdescriptionid=pd.productdescriptionid)) from productdescription pd
union all select 'pmpdc models present in product.productmodelid', count(distinct productmodelid), count(distinct case when productmodelid in (select productmodelid from product where productmodelid<>'') then productmodelid end) from productmodelproductdescriptionculture
union all select 'product models (non-empty) with descriptions', count(distinct productmodelid), count(distinct case when productmodelid in (select productmodelid from productmodelproductdescriptionculture) then productmodelid end) from product where productmodelid<>''
union all select 'review.productid -> product', count(*), sum(p.productid is not null) from productreview r left join product p using(productid)
union all select 'quota.BusinessEntityID -> salesperson', count(*), sum(s.businessentityid is not null) from SalesPersonQuotaHistory q left join salesperson s on s.businessentityid=q.BusinessEntityID
union all select 'salesperson with quota history', count(*), sum(exists(select 1 from SalesPersonQuotaHistory q where q.BusinessEntityID=s.businessentityid)) from salesperson s
union all select 'territory.countryregioncode in countryregioncurrency', count(*), sum(exists(select 1 from countryregioncurrency c where c.countryregioncode=t.countryregioncode)) from salesterritory t
union all select 'currencyrate.tocurrencycode in countryregioncurrency', count(distinct tocurrencycode), count(distinct case when tocurrencycode in (select currencycode from countryregioncurrency) then tocurrencycode end) from currencyrate;

-- name: missing_dimension_tables
-- ids referenced but whose table is not in this subset
select 'customerid' c, count(distinct customerid) from salesorderheader
union all select 'billtoaddressid', count(distinct billtoaddressid) from salesorderheader
union all select 'shiptoaddressid', count(distinct shiptoaddressid) from salesorderheader
union all select 'billto<>shipto', sum(billtoaddressid<>shiptoaddressid) from salesorderheader
union all select 'shipmethodid', count(distinct shipmethodid) from salesorderheader
union all select 'creditcardid', count(distinct creditcardid) from salesorderheader where creditcardid<>''
union all select 'specialofferid', count(distinct specialofferid) from salesorderdetail
union all select 'customers with >1 accountnumber', count(*) from (select customerid from salesorderheader group by 1 having count(distinct accountnumber)>1)
union all select 'customers with >1 territory', count(*) from (select customerid from salesorderheader group by 1 having count(distinct territoryid)>1)
union all select 'customers with >1 billto', count(*) from (select customerid from salesorderheader group by 1 having count(distinct billtoaddressid)>1)
union all select 'customers with both online and offline orders', count(*) from (select customerid from salesorderheader group by 1 having count(distinct onlineorderflag)>1)
union all select 'customers with >1 salesperson', count(*) from (select customerid from salesorderheader where salespersonid<>'' group by 1 having count(distinct salespersonid)>1);

-- name: pmpdc_cultures
select cultureid, count(*), count(distinct productmodelid) from productmodelproductdescriptionculture group by 1 order by 1;

-- name: product_classes
select finishedgoodsflag, makeflag, productsubcategoryid='' no_subcat, count(*) n, sum(exists(select 1 from salesorderdetail d where d.productid=p.productid)) sold
from product p group by 1,2,3 order by 1,2,3;

-- name: sold_vs_sellenddate
select sellenddate, count(*) n, sum(exists(select 1 from salesorderdetail d where d.productid=p.productid)) sold from product p where finishedgoodsflag='t' group by 1;

-- name: detail_rowid_order
-- is the file in salesorderdetailid order, and is detailid contiguous within an order?
select sum(d.salesorderdetailid = d.rowid) rowid_eq_detailid, count(*) n from salesorderdetail d;
-- name: detailid_contiguous_by_order
select count(*) orders, sum(mx-mn+1=n) contiguous, sum(prev_ok) in_header_order from (
  select salesorderid, min(salesorderdetailid) mn, max(salesorderdetailid) mx, count(*) n,
         min(salesorderdetailid) > coalesce(lag(max(salesorderdetailid)) over (order by salesorderid), 0) prev_ok
  from salesorderdetail group by 1);
-- name: header_rowid_order
select sum(salesorderid - 43658 = rowid) id_eq_rowid, count(*) n from salesorderheader;
-- name: header_id_vs_orderdate
select count(*) pairs, sum(orderdate >= prev) nondecreasing from (select orderdate, lag(orderdate) over (order by salesorderid) prev from salesorderheader) where prev is not null;
-- name: detail_id_gaps
select min(salesorderdetailid), max(salesorderdetailid), count(*) from salesorderdetail;
