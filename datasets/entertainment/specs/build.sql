-- entertainment: events → source tables (refdata rebuild, DuckDB).

-- table: Agents
SELECT CAST(ext_id AS BIGINT) AS AgentID, first_name AS AgtFirstName, last_name AS AgtLastName,
       street_address AS AgtStreetAddress, city AS AgtCity, state AS AgtState,
       zip AS AgtZipCode, phone AS AgtPhoneNumber,
       strftime(created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS DateHired, salary AS Salary,
       commission_rate AS CommissionRate
FROM agents;

-- table: Entertainers
SELECT CAST(ext_id AS BIGINT) AS EntertainerID, stage_name AS EntStageName, ssn AS EntSSN,
       street_address AS EntStreetAddress, city AS EntCity, state AS EntState,
       zip AS EntZipCode, phone AS EntPhoneNumber, web_page AS EntWebPage,
       email AS EntEMailAddress,
       strftime(created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS DateEntered
FROM entertainers;

-- table: Members
SELECT CAST(ext_id AS BIGINT) AS MemberID, first_name AS MbrFirstName, last_name AS MbrLastName,
       phone AS MbrPhoneNumber, gender AS Gender
FROM members;

-- table: Entertainer_Members
SELECT CAST(e.ext_id AS BIGINT) AS EntertainerID, CAST(m.ext_id AS BIGINT) AS MemberID,
       x.status AS Status
FROM entertainer_members x JOIN entertainers e USING (entertainer_id) JOIN members m USING (member_id);

-- table: Musical_Styles
SELECT CAST(ext_id AS BIGINT) AS StyleID, style_name AS StyleName FROM musical_styles;

-- table: Entertainer_Styles
SELECT CAST(e.ext_id AS BIGINT) AS EntertainerID, CAST(s.ext_id AS BIGINT) AS StyleID,
       x.style_strength AS StyleStrength
FROM entertainer_styles x JOIN entertainers e USING (entertainer_id)
JOIN musical_styles s USING (style_id);

-- table: Customers
SELECT CAST(ext_id AS BIGINT) AS CustomerID, first_name AS CustFirstName,
       last_name AS CustLastName, street_address AS CustStreetAddress, city AS CustCity,
       state AS CustState, zip AS CustZipCode, phone AS CustPhoneNumber
FROM customers;

-- table: Musical_Preferences
SELECT CAST(c.ext_id AS BIGINT) AS CustomerID, CAST(s.ext_id AS BIGINT) AS StyleID,
       p.preference_seq AS PreferenceSeq
FROM musical_preferences p JOIN customers c USING (customer_id)
JOIN musical_styles s USING (style_id);

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
