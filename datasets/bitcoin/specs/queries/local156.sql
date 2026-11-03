-- local156: yearly average BTC purchase price by region (dollars spent / coins bought, valued at
-- the day's close), the first year of each region dropped; rank per year; % change vs the year
-- before. Written from the question (no gold SQL); the fee-excluded reading, matches gold _d.
WITH tx AS (
  SELECT *, substr(txn_date, 7, 4) || '-' || substr(txn_date, 4, 2) || '-' || substr(txn_date, 1, 2)
            AS d
  FROM bitcoin_transactions),
pr AS (
  SELECT *, substr(market_date, 7, 4) || '-' || substr(market_date, 4, 2) || '-'
            || substr(market_date, 1, 2) AS d
  FROM bitcoin_prices),
y AS (
  SELECT substr(t.d, 1, 4) AS yr, m.region, sum(t.quantity * p.price) / sum(t.quantity) AS avg_price
  FROM tx t JOIN bitcoin_members m USING (member_id)
  JOIN pr p ON p.ticker = t.ticker AND p.d = t.d
  WHERE t.ticker = 'BTC' AND t.txn_type = 'BUY' GROUP BY 1, 2),
z AS (
  SELECT * FROM y WHERE yr > (SELECT min(yr) FROM y y0 WHERE y0.region = y.region))
SELECT yr, region, avg_price, rank() OVER (PARTITION BY yr ORDER BY avg_price DESC) AS rk,
       100.0 * (avg_price / lag(avg_price) OVER (PARTITION BY region ORDER BY yr) - 1) AS pct
FROM z ORDER BY yr, rk, region;
