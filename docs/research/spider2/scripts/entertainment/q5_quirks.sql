-- name: status2_per_entertainer
SELECT n2, count(*) FROM (SELECT EntertainerID, sum(Status=2) n2 FROM Entertainer_Members GROUP BY 1) GROUP BY 1;
-- name: solo_status
SELECT e.EntertainerID, e.EntStageName, m.MemberID, m.Status FROM Entertainer_Members m JOIN Entertainers e USING (EntertainerID) WHERE EntertainerID IN (SELECT EntertainerID FROM Entertainer_Members GROUP BY 1 HAVING count(*)=1);
-- name: cust_member_phone
SELECT c.CustomerID, c.CustFirstName, c.CustLastName, m.MemberID, m.MbrFirstName, m.MbrLastName, c.CustPhoneNumber FROM Customers c JOIN Members m ON m.MbrPhoneNumber=c.CustPhoneNumber;
-- name: outliers
SELECT * FROM Engagements WHERE ContractPrice > 5000 OR julianday(EndDate)-julianday(StartDate) > 20;
-- name: overlap_pairs
SELECT a.EntertainerID, a.EngagementNumber, a.StartDate, a.EndDate, b.EngagementNumber, b.StartDate, b.EndDate FROM Engagements a JOIN Engagements b ON a.EntertainerID=b.EntertainerID AND a.EngagementNumber<b.EngagementNumber AND a.StartDate<=b.EndDate AND b.StartDate<=a.EndDate;
-- name: hired_vs_first_engagement
SELECT (SELECT max(DateHired) FROM Agents) last_hire, (SELECT max(DateEntered) FROM Entertainers) last_entered, (SELECT min(StartDate) FROM Engagements) first_start, (SELECT max(EndDate) FROM Engagements) last_end;
-- name: customer_first_engagement
SELECT CustomerID, min(StartDate) FROM Engagements GROUP BY 1;
-- name: zip_city
SELECT 'agents' k, count(DISTINCT AgtZipCode) FROM Agents UNION ALL SELECT 'customers', count(DISTINCT CustZipCode) FROM Customers UNION ALL SELECT 'entertainers', count(DISTINCT EntZipCode) FROM Entertainers;
-- name: start_time_dist
SELECT StartTime, count(*) FROM Engagements GROUP BY 1;
-- name: hours_dist
SELECT ((CAST(substr(StopTime,1,2) AS INT) - CAST(substr(StartTime,1,2) AS INT) + 24) % 24) hrs, count(*) FROM Engagements GROUP BY 1;
-- name: minutes_nonzero
SELECT count(*) FROM Engagements WHERE substr(StartTime,4) <> '00:00' OR substr(StopTime,4) <> '00:00';
-- name: gap_between_start_dates
WITH s AS (SELECT DISTINCT StartDate d FROM Engagements), g AS (SELECT julianday(lead(d) OVER (ORDER BY d)) - julianday(d) gap FROM s)
SELECT gap, count(*) FROM g WHERE gap IS NOT NULL GROUP BY 1;
-- name: engagements_per_start_date
SELECT n, count(*) FROM (SELECT StartDate, count(*) n FROM Engagements GROUP BY 1) GROUP BY 1;
-- name: customer_agent_affinity
SELECT count(DISTINCT CustomerID||'/'||AgentID) pairs, count(*) FROM Engagements;
-- name: style_matches_customer_pref
-- share of engagements where the entertainer has a style the customer prefers
SELECT sum(EXISTS (SELECT 1 FROM Entertainer_Styles s JOIN Musical_Preferences p USING (StyleID) WHERE s.EntertainerID=e.EntertainerID AND p.CustomerID=e.CustomerID)) matched, count(*) FROM Engagements e;
