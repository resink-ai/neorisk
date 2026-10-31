-- local157: daily % change in volume per ticker, 2021-08-01..10. K/M parsed, '-' = 0, and the
-- previous volume is the last earlier non-zero one. Written from the question (no gold SQL);
-- matches gold _c; _a (08-01 NULL) and _b (no 08-01) differ only on the first day.
WITH pr AS (
  SELECT ticker,
         substr(market_date, 7, 4) || '-' || substr(market_date, 4, 2) || '-'
             || substr(market_date, 1, 2) AS d,
         CASE WHEN volume = '-' THEN 0
              WHEN volume LIKE '%K' THEN CAST(substr(volume, 1, length(volume) - 1) AS REAL) * 1e3
              WHEN volume LIKE '%M' THEN CAST(substr(volume, 1, length(volume) - 1) AS REAL) * 1e6
         END AS vol
  FROM bitcoin_prices),
w AS (
  SELECT ticker, d, vol,
         (SELECT p2.vol FROM pr p2 WHERE p2.ticker = p.ticker AND p2.d < p.d AND p2.vol > 0
          ORDER BY p2.d DESC LIMIT 1) AS prev
  FROM pr p WHERE d BETWEEN '2021-08-01' AND '2021-08-10')
SELECT ticker, d, vol, prev, 100.0 * (vol - prev) / prev AS pct FROM w ORDER BY ticker, d;
