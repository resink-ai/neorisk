-- name: local156_no_fee
-- avg purchase price = sum(qty * close) / sum(qty), BTC BUY, by member region and year (gold _a/_d?)
with y as (
  select substr(t.d,1,4) yr, m.region, sum(t.quantity * p.price) / sum(t.quantity) avg_price
  from tx t join bitcoin_members m using (member_id) join pr p on p.ticker = t.ticker and p.d = t.d
  where t.ticker = 'BTC' and t.txn_type = 'BUY' group by 1, 2)
select yr, region, avg_price, rank() over (partition by yr order by avg_price desc) rk,
  100.0 * (avg_price / lag(avg_price) over (partition by region order by yr) - 1) pct
from y order by yr, rk;
-- name: local156_with_fee
-- dollar amount includes the percentage fee: qty * close * (1 + fee/100)  (gold _b/_c?)
with y as (
  select substr(t.d,1,4) yr, m.region, sum(t.quantity * p.price * (1 + t.percentage_fee / 100.0)) / sum(t.quantity) avg_price
  from tx t join bitcoin_members m using (member_id) join pr p on p.ticker = t.ticker and p.d = t.d
  where t.ticker = 'BTC' and t.txn_type = 'BUY' group by 1, 2)
select yr, region, avg_price, rank() over (partition by yr order by avg_price desc) rk,
  100.0 * (avg_price / lag(avg_price) over (partition by region order by yr) - 1) pct
from y order by yr, rk;
-- name: local157
-- volume K/M parsed, '-' = 0; previous = last earlier non-zero volume; Aug 1..10 2021
with v as (select ticker, d, coalesce(vol, 0) vol from pr),
w as (select ticker, d, vol, (select v2.vol from v v2 where v2.ticker = v.ticker and v2.d < v.d and v2.vol > 0 order by v2.d desc limit 1) prev from v)
select ticker, d, vol, prev, 100.0 * (vol - prev) / prev pct from w where d between '2021-08-01' and '2021-08-10' order by ticker, d;
