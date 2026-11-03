-- Bitcoin trading: events → source tables (refdata rebuild, DuckDB).

-- table: bitcoin_members
SELECT ext_id AS member_id, first_name, region FROM members;

-- table: bitcoin_transactions
SELECT t.txn_id, m.ext_id AS member_id, k.ext_id AS ticker,
       strftime(t.event_time AT TIME ZONE 'UTC', '%d-%m-%Y') AS txn_date,
       CAST(t.txn_type AS VARCHAR) AS txn_type, t.quantity, t.percentage_fee,
       strftime(t.event_time AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S.%gZ') AS txn_time
FROM trade t JOIN members m USING (member_id) JOIN tickers k USING (ticker_id)
ORDER BY t.txn_id;

-- table: bitcoin_prices
SELECT k.ext_id AS ticker, strftime(p.event_time AT TIME ZONE 'UTC', '%d-%m-%Y') AS market_date,
       p.price, p.open, p.high, p.low,
       CASE WHEN p.volume IS NULL THEN '-'
            WHEN p.volume >= 1000000 THEN printf('%.2fM', p.volume / 1e6)
            ELSE printf('%.2fK', p.volume / 1e3) END AS volume,
       printf('%.2f%%', p.change_pct) AS change
FROM price_published p JOIN tickers k USING (ticker_id);
