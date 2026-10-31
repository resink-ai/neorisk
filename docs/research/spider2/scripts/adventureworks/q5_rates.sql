-- name: plus8_orders
select salesorderid, orderdate, shipdate, duedate, revisionnumber, territoryid from salesorderheader
where julianday(shipdate)-julianday(orderdate) <> 7;

-- name: rate_grid_completeness
select count(distinct currencyratedate) dates, count(distinct tocurrencycode) currencies, count(*) rows,
       julianday(max(currencyratedate))-julianday(min(currencyratedate))+1 span_days from currencyrate;
-- name: rates_per_currency
select tocurrencycode, count(*), min(currencyratedate), max(currencyratedate), min(averagerate), max(averagerate),
       sum(averagerate=endofdayrate) avg_eq_eod from currencyrate group by 1 order by 1;
-- name: rate_rows_per_date
select n, count(*) dates from (select currencyratedate, count(*) n from currencyrate group by 1) group by 1;
-- name: rate_id_order
select count(*) pairs, sum(currencyratedate > prevd or (currencyratedate=prevd and tocurrencycode>prevc)) in_date_currency_order
from (select currencyratedate, tocurrencycode, lag(currencyratedate) over (order by currencyrateid) prevd, lag(tocurrencycode) over (order by currencyrateid) prevc from currencyrate) where prevd is not null;
-- name: rate_modifieddate
select sum(modifieddate=currencyratedate) eq, count(*) n from currencyrate;
-- name: rate_modifieddate_diff
select currencyrateid, currencyratedate, modifieddate, tocurrencycode from currencyrate where modifieddate<>currencyratedate limit 10;

-- name: non_us_orders_rate_by_period
select t.countryregioncode<>'US' non_us, h.orderdate <= '2014-05-31 00:00:00' rate_day_exists, h.onlineorderflag,
       count(*) n, sum(h.currencyrateid<>'') with_rate
from salesorderheader h join salesterritory t using(territoryid) group by 1,2,3 order by 1,2,3;

-- name: currency_mismatch
select t.name, h.onlineorderflag, c.tocurrencycode, count(*) from salesorderheader h join currencyrate c on c.currencyrateid=h.currencyrateid
join salesterritory t using(territoryid)
where not exists(select 1 from countryregioncurrency x where x.countryregioncode=t.countryregioncode and x.currencycode=c.tocurrencycode)
group by 1,2,3;

-- name: rate_usage
select count(distinct currencyrateid) used_ids, (select count(*) from currencyrate) all_ids from salesorderheader where currencyrateid<>'';

-- name: countryregioncurrency_multi
select countryregioncode, group_concat(currencycode), count(*) from countryregioncurrency group by 1 having count(*)>1;
-- name: crc_modifieddate
select modifieddate, count(*) from countryregioncurrency group by 1;
-- name: crc_currencies_with_rates
select c.currencycode, c.countryregioncode, c.modifieddate from countryregioncurrency c where c.currencycode in (select tocurrencycode from currencyrate) order by 1;

-- name: rate_daily_change
-- share of days on which the average rate is unchanged from the previous day, per currency
select tocurrencycode, count(*) days, sum(averagerate = prev) unchanged, round(avg(abs(averagerate/prev - 1))*100, 4) mean_abs_pct
from (select tocurrencycode, averagerate, lag(averagerate) over (partition by tocurrencycode order by currencyratedate) prev from currencyrate)
where prev is not null group by 1 order by 1;
-- name: eod_vs_avg
select tocurrencycode, round(avg(endofdayrate/averagerate - 1)*100, 4) mean_pct, round(min(endofdayrate/averagerate - 1)*100,4) min_pct, round(max(endofdayrate/averagerate - 1)*100,4) max_pct
from currencyrate group by 1 order by 1;
-- name: avg_vs_prev_eod
select tocurrencycode, count(*), sum(averagerate = prev_eod) avg_eq_prev_eod
from (select tocurrencycode, averagerate, lag(endofdayrate) over (partition by tocurrencycode order by currencyratedate) prev_eod from currencyrate)
where prev_eod is not null group by 1 order by 1;
