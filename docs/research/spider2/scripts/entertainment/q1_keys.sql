-- name: fk_orphans
SELECT 'eng->customers' fk, count(*) n FROM Engagements WHERE CustomerID NOT IN (SELECT CustomerID FROM Customers)
UNION ALL SELECT 'eng->agents', count(*) FROM Engagements WHERE AgentID NOT IN (SELECT AgentID FROM Agents)
UNION ALL SELECT 'eng->entertainers', count(*) FROM Engagements WHERE EntertainerID NOT IN (SELECT EntertainerID FROM Entertainers)
UNION ALL SELECT 'em->entertainers', count(*) FROM Entertainer_Members WHERE EntertainerID NOT IN (SELECT EntertainerID FROM Entertainers)
UNION ALL SELECT 'em->members', count(*) FROM Entertainer_Members WHERE MemberID NOT IN (SELECT MemberID FROM Members)
UNION ALL SELECT 'es->entertainers', count(*) FROM Entertainer_Styles WHERE EntertainerID NOT IN (SELECT EntertainerID FROM Entertainers)
UNION ALL SELECT 'es->styles', count(*) FROM Entertainer_Styles WHERE StyleID NOT IN (SELECT StyleID FROM Musical_Styles)
UNION ALL SELECT 'mp->customers', count(*) FROM Musical_Preferences WHERE CustomerID NOT IN (SELECT CustomerID FROM Customers)
UNION ALL SELECT 'mp->styles', count(*) FROM Musical_Preferences WHERE StyleID NOT IN (SELECT StyleID FROM Musical_Styles);
-- name: parents_without_children
SELECT 'customers w/o engagements' k, count(*) FROM Customers WHERE CustomerID NOT IN (SELECT CustomerID FROM Engagements)
UNION ALL SELECT 'agents w/o engagements', count(*) FROM Agents WHERE AgentID NOT IN (SELECT AgentID FROM Engagements)
UNION ALL SELECT 'entertainers w/o engagements', count(*) FROM Entertainers WHERE EntertainerID NOT IN (SELECT EntertainerID FROM Engagements)
UNION ALL SELECT 'entertainers w/o styles', count(*) FROM Entertainers WHERE EntertainerID NOT IN (SELECT EntertainerID FROM Entertainer_Styles)
UNION ALL SELECT 'members w/o entertainer', count(*) FROM Members WHERE MemberID NOT IN (SELECT MemberID FROM Entertainer_Members)
UNION ALL SELECT 'styles unused by both', count(*) FROM Musical_Styles WHERE StyleID NOT IN (SELECT StyleID FROM Entertainer_Styles) AND StyleID NOT IN (SELECT StyleID FROM Musical_Preferences)
UNION ALL SELECT 'styles w/o entertainer', count(*) FROM Musical_Styles WHERE StyleID NOT IN (SELECT StyleID FROM Entertainer_Styles)
UNION ALL SELECT 'styles w/o preference', count(*) FROM Musical_Styles WHERE StyleID NOT IN (SELECT StyleID FROM Musical_Preferences)
UNION ALL SELECT 'customers w/o preference', count(*) FROM Customers WHERE CustomerID NOT IN (SELECT CustomerID FROM Musical_Preferences);
-- name: unused_rows
SELECT 'customer' k, CustomerID id, CustLastName nm FROM Customers WHERE CustomerID NOT IN (SELECT CustomerID FROM Engagements)
UNION ALL SELECT 'agent', AgentID, AgtLastName FROM Agents WHERE AgentID NOT IN (SELECT AgentID FROM Engagements)
UNION ALL SELECT 'entertainer', EntertainerID, EntStageName FROM Entertainers WHERE EntertainerID NOT IN (SELECT EntertainerID FROM Engagements)
UNION ALL SELECT 'style unused', StyleID, StyleName FROM Musical_Styles WHERE StyleID NOT IN (SELECT StyleID FROM Entertainer_Styles) AND StyleID NOT IN (SELECT StyleID FROM Musical_Preferences);
-- name: engagement_number_gaps
SELECT min(EngagementNumber), max(EngagementNumber), count(*), max(EngagementNumber)-min(EngagementNumber)+1-count(*) AS missing FROM Engagements;
-- name: missing_numbers
WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<131) SELECT group_concat(x) FROM n WHERE x NOT IN (SELECT EngagementNumber FROM Engagements);
-- name: pref_seq_shape
SELECT CustomerID, count(*) n, group_concat(PreferenceSeq||':'||StyleID) FROM Musical_Preferences GROUP BY 1;
-- name: pref_seq_unique_per_customer
SELECT count(*) FROM (SELECT CustomerID, PreferenceSeq FROM Musical_Preferences GROUP BY 1,2 HAVING count(*)>1);
-- name: style_strength_shape
SELECT EntertainerID, count(*) n, group_concat(StyleStrength||':'||StyleID) FROM Entertainer_Styles GROUP BY 1;
-- name: strength_unique_per_entertainer
SELECT count(*) FROM (SELECT EntertainerID, StyleStrength FROM Entertainer_Styles GROUP BY 1,2 HAVING count(*)>1);
-- name: members_status
SELECT Status, count(*) FROM Entertainer_Members GROUP BY 1;
-- name: members_per_entertainer
SELECT e.EntertainerID, e.EntStageName, count(m.MemberID) members, sum(m.Status=2) status2, group_concat(m.MemberID) FROM Entertainers e LEFT JOIN Entertainer_Members m USING (EntertainerID) GROUP BY 1;
-- name: members_in_many
SELECT MemberID, count(*) FROM Entertainer_Members GROUP BY 1 HAVING count(*)>1;
-- name: agents
SELECT AgentID, AgtFirstName, AgtLastName, DateHired, Salary, CommissionRate, printf('%.17g', CommissionRate) cr17 FROM Agents;
-- name: entertainers
SELECT EntertainerID, EntStageName, DateEntered, EntWebPage, EntEMailAddress, EntZipCode FROM Entertainers;
-- name: members
SELECT * FROM Members;
-- name: people_overlap
SELECT 'cust=member phone' k, count(*) FROM Customers c JOIN Members m ON m.MbrPhoneNumber=c.CustPhoneNumber
UNION ALL SELECT 'cust=member name', count(*) FROM Customers c JOIN Members m ON m.MbrLastName=c.CustLastName AND m.MbrFirstName=c.CustFirstName;
