SELECT m.country, CAST(l.load_dts AS DATE) AS posted_date,
       CAST(count(*) AS BIGINT) AS settlements, CAST(sum(s.net) AS BIGINT) AS net
FROM dv_link_settlement l
JOIN dv_sat_settlement_amounts s USING (settlement_hk)
JOIN dv_sat_merchants_details m USING (merchant_hk)
GROUP BY m.country, CAST(l.load_dts AS DATE);
