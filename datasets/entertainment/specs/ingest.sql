-- entertainment: source tables → events (refdata ingest). T0 = 1995-01-20, the earliest
-- natural date (the first DateEntered). The ztbl* helpers are not ingested: build.sql
-- generates them.

-- entity: agents
SELECT CAST(AgentID AS TEXT) AS ext_id, DateHired || ' 00:00:00' AS created_at,
       AgtFirstName AS first_name, AgtLastName AS last_name, AgtStreetAddress AS street_address,
       AgtCity AS city, AgtState AS state, AgtZipCode AS zip, AgtPhoneNumber AS phone,
       Salary AS salary, CommissionRate AS commission_rate
FROM Agents ORDER BY AgentID;

-- entity: entertainers
SELECT CAST(EntertainerID AS TEXT) AS ext_id, DateEntered || ' 00:00:00' AS created_at,
       EntStageName AS stage_name, EntSSN AS ssn, EntStreetAddress AS street_address,
       EntCity AS city, EntState AS state, EntZipCode AS zip, EntPhoneNumber AS phone,
       EntWebPage AS web_page, EntEMailAddress AS email
FROM Entertainers ORDER BY EntertainerID;

-- entity: members
SELECT CAST(m.MemberID AS TEXT) AS ext_id,
       (SELECT min(e.DateEntered) FROM Entertainer_Members x JOIN Entertainers e USING (EntertainerID)
        WHERE x.MemberID = m.MemberID) || ' 00:00:00' AS created_at,
       MbrFirstName AS first_name, MbrLastName AS last_name, MbrPhoneNumber AS phone,
       Gender AS gender
FROM Members m ORDER BY MemberID;

-- entity: entertainer_members
SELECT x.EntertainerID || '/' || x.MemberID AS ext_id, e.DateEntered || ' 00:00:00' AS created_at,
       CAST(x.EntertainerID AS TEXT) AS entertainer_id, CAST(x.MemberID AS TEXT) AS member_id,
       x.Status AS status
FROM Entertainer_Members x JOIN Entertainers e USING (EntertainerID)
ORDER BY x.EntertainerID, x.MemberID;

-- entity: musical_styles
SELECT CAST(StyleID AS TEXT) AS ext_id, '1995-01-20 00:00:00' AS created_at,
       StyleName AS style_name
FROM Musical_Styles ORDER BY StyleID;

-- entity: entertainer_styles
SELECT x.EntertainerID || '/' || x.StyleID AS ext_id, e.DateEntered || ' 00:00:00' AS created_at,
       CAST(x.EntertainerID AS TEXT) AS entertainer_id, CAST(x.StyleID AS TEXT) AS style_id,
       x.StyleStrength AS style_strength
FROM Entertainer_Styles x JOIN Entertainers e USING (EntertainerID)
ORDER BY x.EntertainerID, x.StyleID;

-- entity: customers
SELECT CAST(c.CustomerID AS TEXT) AS ext_id,
       coalesce((SELECT min(g.StartDate || ' ' || g.StartTime) FROM Engagements g
                 WHERE g.CustomerID = c.CustomerID), '1995-01-20 00:00:00') AS created_at,
       CustFirstName AS first_name, CustLastName AS last_name, CustStreetAddress AS street_address,
       CustCity AS city, CustState AS state, CustZipCode AS zip, CustPhoneNumber AS phone
FROM Customers c ORDER BY CustomerID;

-- entity: musical_preferences
SELECT p.CustomerID || '/' || p.StyleID AS ext_id,
       coalesce((SELECT min(g.StartDate || ' ' || g.StartTime) FROM Engagements g
                 WHERE g.CustomerID = p.CustomerID), '1995-01-20 00:00:00') AS created_at,
       CAST(p.CustomerID AS TEXT) AS customer_id, CAST(p.StyleID AS TEXT) AS style_id,
       p.PreferenceSeq AS preference_seq
FROM Musical_Preferences p ORDER BY p.CustomerID, p.StyleID;

-- event: engagement_booked owner=customer_id ord=engagement_number
SELECT StartDate || ' ' || StartTime AS event_time, CAST(CustomerID AS TEXT) AS customer_id,
       EngagementNumber AS engagement_number, CAST(EntertainerID AS TEXT) AS entertainer_id,
       CAST(AgentID AS TEXT) AS agent_id, EndDate AS end_date, StopTime AS stop_time,
       ContractPrice AS contract_price
FROM Engagements ORDER BY EngagementNumber;
