-- name: row_counts
select 'bitcoin_members' t, count(*) n from bitcoin_members union all
select 'bitcoin_transactions', count(*) from bitcoin_transactions union all
select 'bitcoin_prices', count(*) from bitcoin_prices;
-- name: storage_types
select 'tx' t, typeof(txn_id)||','||typeof(member_id)||','||typeof(ticker)||','||typeof(txn_date)||','||typeof(txn_type)||','||typeof(quantity)||','||typeof(percentage_fee)||','||typeof(txn_time) types, count(*) from bitcoin_transactions group by 2
union all select 'pr', typeof(ticker)||','||typeof(market_date)||','||typeof(price)||','||typeof(open)||','||typeof(high)||','||typeof(low)||','||typeof(volume)||','||typeof(change), count(*) from bitcoin_prices group by 2
union all select 'mem', typeof(member_id)||','||typeof(first_name)||','||typeof(region), count(*) from bitcoin_members group by 2;
-- name: nulls_and_empty
select (select sum(member_id is null or first_name is null or region is null or member_id='' or first_name='' or region='') from bitcoin_members) mem,
 (select sum(txn_id is null)+sum(member_id is null)+sum(ticker is null)+sum(txn_date is null)+sum(txn_type is null)+sum(quantity is null)+sum(percentage_fee is null)+sum(txn_time is null) from bitcoin_transactions) tx,
 (select sum(price is null)+sum(open is null)+sum(high is null)+sum(low is null)+sum(volume is null or volume='')+sum(change is null or change='') from bitcoin_prices) pr;
-- name: members
select rowid, * from bitcoin_members order by rowid;
-- name: member_key
select count(*) n, count(distinct member_id) ids, count(distinct first_name) names from bitcoin_members;
-- name: members_per_region
select region, count(*) from bitcoin_members group by 1 order by 2 desc;
-- name: txn_key
select count(*) n, count(distinct txn_id) ids, min(txn_id), max(txn_id), sum(rowid<>txn_id) rowid_ne_id from bitcoin_transactions;
-- name: txn_full_row_duplicates
select count(*) from (select member_id,ticker,txn_date,txn_type,quantity,percentage_fee,txn_time from bitcoin_transactions group by 1,2,3,4,5,6,7 having count(*)>1);
-- name: price_key
select ticker, count(*) n, count(distinct market_date) days, min(rid), max(rid), min(d), max(d) from pr group by 1;
-- name: price_dup_days
select count(*) from (select ticker, market_date from bitcoin_prices group by 1,2 having count(*)>1);
-- name: price_calendar_gaps
-- consecutive rows per ticker by date: gaps other than 1 day
select ticker, gap, count(*) from (select ticker, julianday(d) - julianday(lag(d) over (partition by ticker order by d)) gap from pr) where gap is not null group by 1,2 order by 1,2;
-- name: fk_member
select (select count(*) from bitcoin_transactions where member_id not in (select member_id from bitcoin_members)) orphans,
       (select count(*) from bitcoin_members where member_id not in (select member_id from bitcoin_transactions)) members_without_tx;
-- name: fk_price_day
select count(*) tx, sum(p.ticker is null) without_price_row from tx t left join pr p on p.ticker=t.ticker and p.d=t.d;
-- name: categoricals
select 'ticker' c, ticker v, count(*) from bitcoin_transactions group by 2
union all select 'txn_type', txn_type, count(*) from bitcoin_transactions group by 2
union all select 'ticker×type', ticker||' '||txn_type, count(*) from bitcoin_transactions group by 2;
-- name: date_formats
select 'txn_date not DD-MM-YYYY' k, count(*) from bitcoin_transactions where txn_date not glob '[0-3][0-9]-[01][0-9]-20[12][0-9]'
union all select 'txn_time not ISO-ms-Z', count(*) from bitcoin_transactions where txn_time not glob '20[12][0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9].[0-9][0-9][0-9]Z'
union all select 'txn_date <> date(txn_time)', count(*) from tx where d <> substr(txn_time,1,10)
union all select 'market_date not DD-MM-YYYY', count(*) from bitcoin_prices where market_date not glob '[0-3][0-9]-[01][0-9]-20[12][0-9]'
union all select 'invalid calendar date (tx)', count(*) from tx where date(d) is null or date(d)<>d
union all select 'invalid calendar date (pr)', count(*) from pr where date(d) is null or date(d)<>d;
-- name: tx_time_range
select min(txn_time), max(txn_time), min(d), max(d) from tx;
-- name: physical_order_prices
-- rows: ETH first, then BTC; within each, date descending?
select ticker, sum(d >= lag_d) non_desc_steps, sum(d < lag_d) desc_steps from (select ticker, d, lag(d) over (order by rid) lag_d, lag(ticker) over (order by rid) lt from pr) where lt=ticker group by 1;
