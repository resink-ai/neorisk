-- local132: entertainer and customer pairs where the customer's 1st and 2nd preferences equal
-- the entertainer's 1st and 2nd style strengths, in either order; both sides have at most 3
-- styles. The entertainer's stage name and the customer's last name.
-- Written from the question (no gold SQL). Reproduces gold variant local132_a.csv, 6 of 6 rows.
WITH e AS (SELECT EntertainerID, max(CASE WHEN StyleStrength = 1 THEN StyleID END) AS s1,
                  max(CASE WHEN StyleStrength = 2 THEN StyleID END) AS s2
           FROM Entertainer_Styles GROUP BY 1 HAVING count(*) <= 3),
c AS (SELECT CustomerID, max(CASE WHEN PreferenceSeq = 1 THEN StyleID END) AS p1,
             max(CASE WHEN PreferenceSeq = 2 THEN StyleID END) AS p2
      FROM Musical_Preferences GROUP BY 1 HAVING count(*) <= 3)
SELECT t.EntStageName, u.CustLastName
FROM e JOIN c ON (e.s1 = c.p1 AND e.s2 = c.p2) OR (e.s1 = c.p2 AND e.s2 = c.p1)
JOIN Entertainers t USING (EntertainerID) JOIN Customers u USING (CustomerID);
