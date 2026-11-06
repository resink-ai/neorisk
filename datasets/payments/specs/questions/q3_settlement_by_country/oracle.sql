-- Settlements posted and their net payout per merchant country and UTC day.
SELECT m.country, CAST(s.event_time AS DATE) AS posted_date,
       CAST(count(*) AS BIGINT) AS settlements, CAST(sum(s.net) AS BIGINT) AS net
FROM sim.settlement_posted s JOIN sim.merchants m USING (merchant_id)
GROUP BY m.country, CAST(s.event_time AS DATE);
