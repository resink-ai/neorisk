-- name: formats
SELECT length(StartDate) ls, length(EndDate) le, length(StartTime) lt, length(StopTime) lp, count(*) FROM Engagements GROUP BY 1,2,3,4;
-- name: date_order
SELECT sum(EndDate < StartDate) end_before_start, sum(EndDate = StartDate) same_day, sum(EndDate > StartDate) multi_day FROM Engagements;
-- name: days_dist
SELECT CAST(julianday(EndDate)-julianday(StartDate) AS INT)+1 AS days, count(*) FROM Engagements GROUP BY 1 ORDER BY 1;
-- name: times
SELECT StartTime, StopTime, count(*) FROM Engagements GROUP BY 1,2 ORDER BY 3 DESC;
-- name: stop_before_start
SELECT count(*) FROM Engagements WHERE StopTime <= StartTime;
-- name: price_vs_days_hours
-- is ContractPrice a function of days x hours x rate?
SELECT EngagementNumber, StartDate, EndDate, StartTime, StopTime, ContractPrice, EntertainerID,
  CAST(julianday(EndDate)-julianday(StartDate) AS INT)+1 days,
  ((CAST(substr(StopTime,1,2) AS INT) - CAST(substr(StartTime,1,2) AS INT) + 24) % 24) hrs
FROM Engagements ORDER BY EngagementNumber LIMIT 30;
-- name: price_per_day_hour
WITH e AS (SELECT *, CAST(julianday(EndDate)-julianday(StartDate) AS INT)+1 days,
  ((CAST(substr(StopTime,1,2) AS INT)*60+CAST(substr(StopTime,4,2) AS INT) - CAST(substr(StartTime,1,2) AS INT)*60-CAST(substr(StartTime,4,2) AS INT) + 1440) % 1440) mins FROM Engagements)
SELECT EntertainerID, count(*) n, count(DISTINCT ContractPrice) prices, group_concat(DISTINCT round(1.0*ContractPrice/(days*mins/60.0),3)) per_hour_day FROM e GROUP BY 1;
-- name: price_last_digit
SELECT ContractPrice % 10 d, count(*) FROM Engagements GROUP BY 1;
-- name: number_vs_startdate
SELECT sum(nxt_sd >= StartDate) nondecreasing, count(*) pairs FROM (SELECT StartDate, lead(StartDate) OVER (ORDER BY EngagementNumber) nxt_sd FROM Engagements) WHERE nxt_sd IS NOT NULL;
-- name: per_month
SELECT substr(StartDate,1,7) m, count(*), sum(ContractPrice) FROM Engagements GROUP BY 1;
-- name: weekday
SELECT strftime('%w', StartDate) dow, count(*) FROM Engagements GROUP BY 1;
-- name: entertainer_overlap
-- does an entertainer have two engagements whose date ranges overlap?
SELECT count(*) FROM Engagements a JOIN Engagements b ON a.EntertainerID=b.EntertainerID AND a.EngagementNumber<b.EngagementNumber AND a.StartDate<=b.EndDate AND b.StartDate<=a.EndDate;
-- name: engagements_before_entered_or_hired
SELECT sum(e.StartDate < t.DateEntered) before_entered, sum(e.StartDate < a.DateHired) before_hired, count(*) FROM Engagements e JOIN Entertainers t USING (EntertainerID) JOIN Agents a USING (AgentID);
-- name: per_customer
SELECT CustomerID, count(*) FROM Engagements GROUP BY 1 ORDER BY 2 DESC;
-- name: per_agent
SELECT AgentID, count(*), sum(ContractPrice) FROM Engagements GROUP BY 1;
-- name: per_entertainer
SELECT EntertainerID, count(*), sum(ContractPrice) FROM Engagements GROUP BY 1;
-- name: price_quantiles
WITH r AS (SELECT ContractPrice p, row_number() OVER (ORDER BY ContractPrice) i, count(*) OVER () n FROM Engagements)
SELECT max(CASE WHEN i = CAST(0.1*n AS INT) THEN p END) p10, max(CASE WHEN i = CAST(0.5*n AS INT) THEN p END) p50, max(CASE WHEN i = CAST(0.9*n AS INT) THEN p END) p90, min(p), max(p), avg(p) FROM r;
-- name: lead_time_unknown
-- no booking date exists: check columns
SELECT group_concat(name) FROM pragma_table_info('Engagements');
