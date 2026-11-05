-- Bitcoin trading: source tables → events (refdata ingest).
-- Snapshots at N = 2021-08-29 00:00:00, the last price bar (a rule).

-- entity: tickers
SELECT DISTINCT ticker AS ext_id FROM bitcoin_prices ORDER BY ticker;

-- entity: members
SELECT member_id AS ext_id, first_name FROM bitcoin_members ORDER BY member_id;

-- event: price_published owner=ticker_id
-- Volume is parsed from its digits: 2 decimals always, so K → ×10 and M → ×10 000 of the integer.
SELECT substr(market_date, 7, 4) || '-' || substr(market_date, 4, 2) || '-'
           || substr(market_date, 1, 2) || ' 00:00:00' AS event_time,
       ticker AS ticker_id, price, open, high, low,
       CASE WHEN volume = '-' THEN NULL
            ELSE CAST(replace(substr(volume, 1, length(volume) - 1), '.', '') AS INTEGER)
                 * CASE substr(volume, -1) WHEN 'K' THEN 10 WHEN 'M' THEN 10000 END
       END AS volume,
       CAST(substr(change, 1, length(change) - 1) AS REAL) AS change_pct
FROM bitcoin_prices ORDER BY ticker, event_time;

-- event: trade owner=member_id ord=txn_id
SELECT iso_time(txn_time, '%Y-%m-%dT%H:%M:%S.%fZ') AS event_time, member_id, ticker AS ticker_id,
       txn_type, quantity, percentage_fee, txn_id
FROM bitcoin_transactions ORDER BY txn_id;

-- event: members_snapshot owner=member_id
SELECT '2021-08-29 00:00:00' AS event_time, member_id, region
FROM bitcoin_members ORDER BY member_id;
