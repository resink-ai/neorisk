-- entertainment: events → source tables (refdata rebuild, DuckDB).

-- table: Agents
-- Address, phone, salary and commission rate are the snapshot at N.
SELECT CAST(a.ext_id AS BIGINT) AS AgentID, a.first_name AS AgtFirstName,
       a.last_name AS AgtLastName, n.street_address AS AgtStreetAddress, n.city AS AgtCity,
       n.state AS AgtState, n.zip AS AgtZipCode, n.phone AS AgtPhoneNumber,
       strftime(a.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS DateHired, n.salary AS Salary,
       n.commission_rate AS CommissionRate
FROM agents a LEFT JOIN agents_snapshot n USING (agent_id);

-- table: Entertainers
-- Address and contact details are the snapshot at N.
SELECT CAST(e.ext_id AS BIGINT) AS EntertainerID, e.stage_name AS EntStageName, e.ssn AS EntSSN,
       n.street_address AS EntStreetAddress, n.city AS EntCity, n.state AS EntState,
       n.zip AS EntZipCode, n.phone AS EntPhoneNumber, n.web_page AS EntWebPage,
       n.email AS EntEMailAddress,
       strftime(e.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS DateEntered
FROM entertainers e LEFT JOIN entertainers_snapshot n USING (entertainer_id);

-- table: Members
-- The phone is the snapshot at N.
SELECT CAST(m.ext_id AS BIGINT) AS MemberID, m.first_name AS MbrFirstName,
       m.last_name AS MbrLastName, n.phone AS MbrPhoneNumber, m.gender AS Gender
FROM members m LEFT JOIN members_snapshot n USING (member_id);

-- table: Entertainer_Members
SELECT CAST(e.ext_id AS BIGINT) AS EntertainerID, CAST(m.ext_id AS BIGINT) AS MemberID,
       n.status AS Status
FROM entertainer_members x JOIN entertainers e USING (entertainer_id) JOIN members m USING (member_id)
LEFT JOIN entertainer_members_snapshot n USING (em_id);

-- table: Musical_Styles
SELECT CAST(ext_id AS BIGINT) AS StyleID, style_name AS StyleName FROM musical_styles;

-- table: Entertainer_Styles
SELECT CAST(e.ext_id AS BIGINT) AS EntertainerID, CAST(s.ext_id AS BIGINT) AS StyleID,
       n.style_strength AS StyleStrength
FROM entertainer_styles x JOIN entertainers e USING (entertainer_id)
JOIN musical_styles s USING (style_id) LEFT JOIN entertainer_styles_snapshot n USING (es_id);

-- table: Customers
-- Address and phone are the snapshot at N.
SELECT CAST(c.ext_id AS BIGINT) AS CustomerID, c.first_name AS CustFirstName,
       c.last_name AS CustLastName, n.street_address AS CustStreetAddress, n.city AS CustCity,
       n.state AS CustState, n.zip AS CustZipCode, n.phone AS CustPhoneNumber
FROM customers c LEFT JOIN customers_snapshot n USING (customer_id);

-- table: Musical_Preferences
SELECT CAST(c.ext_id AS BIGINT) AS CustomerID, CAST(s.ext_id AS BIGINT) AS StyleID,
       n.preference_seq AS PreferenceSeq
FROM musical_preferences p JOIN customers c USING (customer_id)
JOIN musical_styles s USING (style_id) LEFT JOIN musical_preferences_snapshot n USING (mp_id);

-- table: Engagements
-- The event time is the performance start; the end stays as text (17 end after midnight).
SELECT g.engagement_number AS EngagementNumber,
       strftime(g.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS StartDate,
       g.end_date AS EndDate, strftime(g.event_time AT TIME ZONE 'UTC', '%H:%M:%S') AS StartTime,
       g.stop_time AS StopTime, g.contract_price AS ContractPrice,
       CAST(c.ext_id AS BIGINT) AS CustomerID, CAST(a.ext_id AS BIGINT) AS AgentID,
       CAST(e.ext_id AS BIGINT) AS EntertainerID
FROM engagement_booked g JOIN customers c USING (customer_id) JOIN agents a USING (agent_id)
JOIN entertainers e USING (entertainer_id);

-- table: ztblDays
-- The four helpers are generated, not logged. Their ranges are constants copied from the
-- source: days 2017-01-01 .. 2020-01-01, 156 weeks, 36 months, labels 1..60.
SELECT strftime(d, '%Y-%m-%d') AS DateField
FROM generate_series(DATE '2017-01-01', DATE '2020-01-01', INTERVAL 1 DAY) t(d);

-- table: ztblWeeks
-- Sunday-to-Saturday weeks from 2017-01-01, a Sunday.
SELECT strftime(d, '%Y-%m-%d') AS WeekStart, strftime(d + INTERVAL 6 DAY, '%Y-%m-%d') AS WeekEnd
FROM generate_series(DATE '2017-01-01', DATE '2019-12-22', INTERVAL 7 DAY) t(d);

-- table: ztblMonths
SELECT strftime(d, '%B %Y') AS MonthYear, year(d)::BIGINT AS YearNumber,
       month(d)::BIGINT AS MonthNumber, strftime(d, '%Y-%m-%d') AS MonthStart,
       strftime(last_day(d), '%Y-%m-%d') AS MonthEnd,
       (month(d) = 1)::BIGINT AS January, (month(d) = 2)::BIGINT AS February,
       (month(d) = 3)::BIGINT AS March, (month(d) = 4)::BIGINT AS April,
       (month(d) = 5)::BIGINT AS May, (month(d) = 6)::BIGINT AS June,
       (month(d) = 7)::BIGINT AS July, (month(d) = 8)::BIGINT AS August,
       (month(d) = 9)::BIGINT AS September, (month(d) = 10)::BIGINT AS October,
       (month(d) = 11)::BIGINT AS November, (month(d) = 12)::BIGINT AS December
FROM generate_series(DATE '2017-01-01', DATE '2019-12-01', INTERVAL 1 MONTH) t(d);

-- table: ztblSkipLabels
SELECT range::BIGINT AS LabelCount FROM range(1, 61);
