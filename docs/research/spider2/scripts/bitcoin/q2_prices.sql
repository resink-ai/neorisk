-- name: volume_suffix
select ticker, case when volume='-' then '-' else substr(volume,-1) end suf, count(*), min(vol), max(vol) from pr group by 1,2 order by 1,2;
-- name: volume_mantissa_decimals
-- digits after the decimal point in the mantissa (K/M stripped)
select ticker, substr(volume,-1) suf,
  case when instr(volume,'.')=0 then 0 else length(volume)-instr(volume,'.')-1 end decs, count(*) from pr where volume<>'-' group by 1,2,3 order by 1,2,3;
-- name: volume_mantissa_range
-- K mantissa < 1000 and M mantissa >= 1 always? (Investing.com style switch at 1M)
select ticker, substr(volume,-1) suf, min(cast(substr(volume,1,length(volume)-1) as real)) lo, max(cast(substr(volume,1,length(volume)-1) as real)) hi from pr where volume<>'-' group by 1,2;
-- name: volume_dash_row
select rid, * from pr where volume='-';
-- name: volume_dash_neighbours
select rid, ticker, market_date, price, open, high, low, volume, change from pr where ticker='ETH' and d between '2017-11-23' and '2017-11-29' order by d;
-- name: volume_tiny
-- smallest parsed volumes per ticker (spikes in local157)
select ticker, market_date, volume, vol, price from pr where vol is not null order by vol limit 12;
-- name: volume_jumps
-- day-over-day volume ratio extremes
select ticker, market_date, volume, prev_volume, round(vol/pv,4) ratio from (select *, lag(vol) over (partition by ticker order by d) pv, lag(volume) over (partition by ticker order by d) prev_volume from pr) where pv>0 and (vol/pv>20 or vol/pv<0.05) order by ticker, d;
-- name: local157_window
select ticker, d, volume, vol, change from pr where d between '2021-07-30' and '2021-08-10' order by ticker, d;
-- name: change_format
select ticker, case when change glob '-*' then 'neg' else 'nonneg' end sign,
  length(change)-instr(change,'.')-1 decs, count(*) from pr group by 1,2,3;
-- name: change_plus_sign
select count(*) from pr where change glob '+*';
-- name: change_vs_close
-- change == round(100*(price/prev_price - 1), 2)? (exact in 2-dp text)
select ticker, count(*) n,
  sum(printf('%.2f%%', 100.0*(price/pp - 1)) = change) exact_text,
  sum(abs(100.0*(price/pp-1) - chg) <= 0.005 + 1e-9) within_half_bp,
  sum(abs(100.0*(price/pp-1) - chg) > 0.011) off_by_more_than_1bp,
  max(abs(100.0*(price/pp-1) - chg)) max_abs_diff
from (select *, lag(price) over (partition by ticker order by d) pp from pr) where pp is not null group by 1;
-- name: change_mismatches
select ticker, market_date, pp, price, change, printf('%.4f', 100.0*(price/pp - 1)) recomputed from (select *, lag(price) over (partition by ticker order by d) pp from pr) where pp is not null and abs(100.0*(price/pp-1) - chg) > 0.011 order by ticker, d limit 30;
-- name: change_negative_zero
select ticker, market_date, change from pr where change in ('-0.00%','0.00%') order by ticker, d;
-- name: change_first_day
select ticker, market_date, open, price, change, printf('%.2f%%', 100.0*(price/open-1)) vs_open from pr where d='2017-01-01';
-- name: open_vs_prev_close
select ticker, count(*) n, sum(open = pp) open_eq_prev_close, sum(abs(open-pp)/pp < 0.001) within_10bp, sum(abs(open-pp)/pp > 0.01) off_gt_1pct from (select *, lag(price) over (partition by ticker order by d) pp from pr) where pp is not null group by 1;
-- name: open_vs_prev_close_worst
select ticker, market_date, pp prev_close, open, round(100*(open-pp)/pp,3) pct from (select *, lag(price) over (partition by ticker order by d) pp from pr) where pp is not null and abs(open-pp)/pp > 0.01 order by abs(open-pp)/pp desc limit 12;
-- name: ohlc_consistency
select ticker, count(*) n, sum(low <= min(open,price) and high >= max(open,price) and low <= high) consistent,
  sum(high = low) flat_days from pr group by 1;
-- name: ohlc_violations
select ticker, market_date, open, high, low, price from pr where not (low <= min(open,price) and high >= max(open,price)) order by ticker, d limit 20;
-- name: price_decimals
-- digits after the decimal point when printed as shortest repr ('%!.15g')
select ticker, length(cast(price as text)) - instr(cast(price as text),'.') decs, count(*) from pr group by 1,2 order by 1,2;
-- name: price_range_by_year
select ticker, substr(d,1,4) y, count(*), min(price), max(price), round(avg(price),2) avg, round(avg(vol),0) avg_vol from pr group by 1,2 order by 1,2;
