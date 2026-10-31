-- name: initial_buys
-- rows at exactly midnight
select count(*) n, count(distinct member_id) members, count(distinct ticker) tickers, min(txn_id), max(txn_id), min(quantity), max(quantity), group_concat(distinct txn_type) types, min(d), max(d)
from tx where substr(txn_time,12) = '00:00:00.000Z';
-- name: initial_buys_order
select txn_id, member_id, ticker, quantity, percentage_fee from tx where txn_id <= 28 order by txn_id;
-- name: qty_50
select count(*) n_qty_50, sum(txn_id<=28) in_first_28 from tx where quantity = 50;
-- name: id_vs_time
-- consecutive txn_id: is txn_time non-decreasing?
select count(*) pairs, sum(t >= pt) nondecreasing, sum(t < pt) descents, sum(t = pt) ties, sum(d < pd) date_descents from (select txn_time t, d, lag(txn_time) over (order by txn_id) pt, lag(d) over (order by txn_id) pd from tx) where pt is not null;
-- name: id_vs_time_descents
select txn_id, txn_time, pt prev_time, ticker, member_id from (select txn_id, txn_time, ticker, member_id, lag(txn_time) over (order by txn_id) pt from tx) where txn_time < pt order by txn_id limit 20;
-- name: time_ties
select count(*) tie_groups, sum(n) rows_in_ties, max(n) from (select txn_time, count(*) n from tx group by 1 having n > 1);
-- name: time_ties_excl_midnight
select count(*) tie_groups, sum(n) rows_in_ties from (select txn_time, count(*) n from tx where txn_id > 28 group by 1 having n > 1);
-- name: rank_by_time_equals_id
-- does txn_id equal the rank of (txn_time, txn_id)?
select sum(rk = txn_id) eq, count(*) n from (select txn_id, row_number() over (order by txn_time, txn_id) rk from tx);
-- name: ms_digits
select substr(txn_time, 21, 3) = '000' ms_zero, count(*) from tx where txn_id > 28 group by 1;
-- name: hour_of_day
select cast(substr(txn_time,12,2) as int) h, count(*) from tx where txn_id > 28 group by 1 order by 1;
-- name: rows_per_day
select n, count(*) days from (select d, count(*) n from tx where txn_id > 28 group by 1) group by 1 order by 1;
-- name: days_without_tx
select count(*) from pr p where p.ticker='BTC' and p.d between '2017-01-01' and '2021-08-27' and not exists (select 1 from tx t where t.d = p.d);
-- name: rows_per_member_ticker_day
select n, count(*) from (select member_id, ticker, d, count(*) n from tx group by 1,2,3) group by 1 order by 1;
-- name: per_member
select m.rowid mrow, member_id, first_name, region, count(*) n, sum(ticker='BTC') btc, sum(txn_type='SELL') sells,
  round(sum(case when txn_type='BUY' then quantity else -quantity end * (ticker='BTC')),4) btc_net,
  round(sum(case when txn_type='BUY' then quantity else -quantity end * (ticker='ETH')),4) eth_net,
  min(d) first_d, max(d) last_d
from tx join bitcoin_members m using (member_id) group by member_id order by mrow;
-- name: fee_by_member
select member_id, count(*) n, sum(percentage_fee = 0.3) fee_03, count(distinct percentage_fee) distinct_fees, round(avg(percentage_fee),4) avg_fee from tx group by 1 order by 1;
-- name: fee_by_year
select substr(d,1,4) y, count(*), sum(percentage_fee=0.3) fee_03, round(1.0*sum(percentage_fee=0.3)/count(*),4) share_03, round(avg(percentage_fee),4) from tx group by 1;
-- name: fee_by_type_ticker
select ticker, txn_type, count(*), round(1.0*sum(percentage_fee=0.3)/count(*),4) share_03, round(avg(case when percentage_fee<0.3 then percentage_fee end),4) avg_low from tx group by 1,2;
-- name: fee_values_two_decimals
select count(*) from tx where abs(percentage_fee*100 - round(percentage_fee*100)) > 1e-9;
-- name: fee_low_uniform
-- fees below 0.3: 0.00..0.29 counts (uniform over 30 values?)
select min(c), max(c), avg(c), count(*) vals from (select percentage_fee, count(*) c from tx where percentage_fee < 0.3 group by 1);
-- name: qty_decimals
select length(cast(quantity as text)) - instr(cast(quantity as text),'.') decs, count(*) from tx group by 1 order by 1;
-- name: qty_by_type
select ticker, txn_type, count(*), min(quantity), max(quantity), round(avg(quantity),4) mean from tx where txn_id > 28 group by 1,2;
-- name: qty_hist_buy
select ticker, txn_type, cast(quantity as int) bucket, count(*) from tx where txn_id > 28 group by 1,2,3 order by 1,2,3;
-- name: holdings_nonneg_by_id
-- running holdings per member and ticker in txn_id order
select count(*) neg_rows, min(h) min_holding from (select sum(case when txn_type='BUY' then quantity else -quantity end) over (partition by member_id, ticker order by txn_id) h from tx) where h < -1e-9;
-- name: holdings_nonneg_by_time
select count(*) neg_rows, min(h) from (select sum(case when txn_type='BUY' then quantity else -quantity end) over (partition by member_id, ticker order by txn_time, txn_id) h from tx) where h < -1e-9;
-- name: sell_vs_holding
-- sell quantity relative to the holding just before it
select round(q/hb, 1) frac, count(*) from (select txn_type, quantity q, sum(case when txn_type='BUY' then quantity else -quantity end) over (partition by member_id, ticker order by txn_id rows between unbounded preceding and 1 preceding) hb from tx) where txn_type='SELL' group by 1 order by 1;
-- name: sell_max_frac
select max(q/hb), min(hb - q) min_left from (select txn_type, quantity q, sum(case when txn_type='BUY' then quantity else -quantity end) over (partition by member_id, ticker order by txn_id rows between unbounded preceding and 1 preceding) hb from tx) where txn_type='SELL';
-- name: tx_after_prices
select count(*) from tx where d > (select max(d) from pr);
-- name: monthly_volume
select substr(d,1,7) m, count(*) n, sum(txn_type='SELL') sells from tx where txn_id > 28 group by 1 order by 1;
-- name: yearly
select substr(d,1,4) y, count(*), sum(txn_type='SELL'), round(1.0*sum(txn_type='SELL')/count(*),4) sell_share from tx where txn_id > 28 group by 1;
-- name: interarrival_seconds
-- gap between consecutive transactions (global, by time), excluding the 28 openers
select case when g < 60 then '<1m' when g < 600 then '1-10m' when g < 3600 then '10-60m' when g < 4*3600 then '1-4h' when g < 86400 then '4-24h' else '>=1d' end b, count(*), round(avg(g),1)
from (select (julianday(substr(txn_time,1,23)) - julianday(lag(substr(txn_time,1,23)) over (order by txn_time, txn_id)))*86400 g from tx where txn_id > 28) where g is not null group by 1 order by 2 desc;
-- name: gap_moments
select count(*), round(avg(g),1) mean_s, round(sqrt(avg(g*g)-avg(g)*avg(g)),1) sd_s, round(max(g),0) max_s
from (select (julianday(substr(txn_time,1,23)) - julianday(lag(substr(txn_time,1,23)) over (order by txn_time, txn_id)))*86400 g from tx where txn_id > 28) where g is not null;
-- name: member_share_by_time
select member_id, round(1.0*count(*)/(select count(*) from tx where txn_id>28),4) share from tx where txn_id>28 group by 1 order by 2 desc;
