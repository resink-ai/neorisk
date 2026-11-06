SELECT symbol, CAST(load_dts AS DATE) AS trade_date, CAST(count(*) AS BIGINT) AS trades,
       CAST(sum(qty) AS BIGINT) AS qty, CAST(sum(price * qty) AS BIGINT) AS notional
FROM dv_sat_trade_details
GROUP BY symbol, trade_date;
