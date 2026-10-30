.mode list
.headers on
select * from bitcoin_members;
select ticker, txn_type, count(*), round(sum(quantity),2) qty, min(txn_date), max(txn_date), round(avg(percentage_fee),3) fee, min(quantity), max(quantity) from bitcoin_transactions group by 1,2;
select count(distinct txn_id), min(txn_id), max(txn_id), count(*) from bitcoin_transactions;
select count(*) bad_member from bitcoin_transactions where member_id not in (select member_id from bitcoin_members);
select substr(txn_time,12,12) tod, count(*) from bitcoin_transactions group by 1 order by 2 desc limit 3;
select count(*) date_mismatch from bitcoin_transactions where substr(txn_date,7,4)||'-'||substr(txn_date,4,2)||'-'||substr(txn_date,1,2) <> substr(txn_time,1,10);
select ticker, count(*), min(substr(market_date,7,4)||substr(market_date,4,2)||substr(market_date,1,2)), max(substr(market_date,7,4)||substr(market_date,4,2)||substr(market_date,1,2)), sum(volume='-') from bitcoin_prices group by 1;
select count(*) txn_without_price from bitcoin_transactions t where not exists (select 1 from bitcoin_prices p where p.ticker=t.ticker and p.market_date=t.txn_date);
-- running holdings per member/ticker going negative
with x as (select member_id, ticker, txn_id, sum(case when txn_type='BUY' then quantity else -quantity end) over (partition by member_id, ticker order by txn_time, txn_id) h from bitcoin_transactions) select count(*) neg_rows, count(distinct member_id||ticker) from x where h < -1e-9;
select percentage_fee, count(*) from bitcoin_transactions group by 1 order by 2 desc limit 5;
select count(*) n_txn_per_day_mean from (select txn_date from bitcoin_transactions group by 1);
-- weekly_sales vs cleaned
select count(*), min(week_date), max(week_date), count(distinct week_date) from weekly_sales;
select count(*) from weekly_sales w where not exists (select 1 from cleaned_weekly_sales c where c.week_date=w.week_date and c.region=w.region and c.platform=w.platform and c.segment=w.segment and c.customer_type=w.customer_type and c.transactions=w.transactions and c.sales=w.sales);
select * from cleaned_weekly_sales limit 2;
select count(*), count(distinct interest_id), min(month_year), max(month_year), sum(_month is null) from interest_metrics;
select * from interest_map limit 2;
select min(txn_date), max(txn_date), count(distinct item_code), sum("sale/return"<>'sale') from veg_txn_df;
select * from veg_txn_df limit 2;
