-- name: local131
-- Spider's gold SQL (gold/local131.sql) plus StyleID, matching the _a CSV's columns. Note: gold CSV includes styles with 0 counts.
SELECT s.StyleID, s.StyleName, count(CASE WHEN p.PreferenceSeq=1 THEN 1 END) FirstPreferenceCount, count(CASE WHEN p.PreferenceSeq=2 THEN 1 END) SecondPreferenceCount, count(CASE WHEN p.PreferenceSeq=3 THEN 1 END) ThirdPreferenceCount
FROM Musical_Styles s LEFT JOIN Musical_Preferences p USING (StyleID) GROUP BY s.StyleID, s.StyleName;
-- name: local131_gold_sql
SELECT 
  Musical_Styles.StyleName,
  COUNT(RankedPreferences.FirstStyle) AS FirstPreference,
  COUNT(RankedPreferences.SecondStyle) AS SecondPreference,
  COUNT(RankedPreferences.ThirdStyle) AS ThirdPreference
FROM Musical_Styles,
 (SELECT (CASE WHEN Musical_Preferences.PreferenceSeq = 1 THEN Musical_Preferences.StyleID ELSE Null END) As FirstStyle,
         (CASE WHEN Musical_Preferences.PreferenceSeq = 2 THEN Musical_Preferences.StyleID ELSE Null END) As SecondStyle,
         (CASE WHEN Musical_Preferences.PreferenceSeq = 3 THEN Musical_Preferences.StyleID ELSE Null END) AS ThirdStyle
   FROM Musical_Preferences) AS RankedPreferences
WHERE Musical_Styles.StyleID = RankedPreferences.FirstStyle OR Musical_Styles.StyleID = RankedPreferences.SecondStyle OR Musical_Styles.StyleID = RankedPreferences.ThirdStyle
GROUP BY StyleID, StyleName
HAVING COUNT(FirstStyle) > 0 OR COUNT(SecondStyle) > 0 OR COUNT(ThirdStyle) > 0
ORDER BY FirstPreference DESC, SecondPreference DESC, ThirdPreference DESC, StyleID;
-- name: local132
-- entertainers' strengths 1,2 = customers' preferences 1,2, same or swapped order; both sides have <= 3 rows
WITH e AS (SELECT EntertainerID, max(CASE WHEN StyleStrength=1 THEN StyleID END) s1, max(CASE WHEN StyleStrength=2 THEN StyleID END) s2 FROM Entertainer_Styles GROUP BY 1 HAVING count(*) <= 3),
c AS (SELECT CustomerID, max(CASE WHEN PreferenceSeq=1 THEN StyleID END) p1, max(CASE WHEN PreferenceSeq=2 THEN StyleID END) p2 FROM Musical_Preferences GROUP BY 1 HAVING count(*) <= 3)
SELECT t.EntStageName, u.CustLastName FROM e JOIN c ON (e.s1=c.p1 AND e.s2=c.p2) OR (e.s1=c.p2 AND e.s2=c.p1)
JOIN Entertainers t USING (EntertainerID) JOIN Customers u USING (CustomerID);
-- name: local133
WITH w AS (SELECT StyleID, sum(CASE PreferenceSeq WHEN 1 THEN 3 WHEN 2 THEN 2 WHEN 3 THEN 1 END) score FROM Musical_Preferences GROUP BY 1)
SELECT s.StyleName, abs(score - (SELECT avg(score) FROM w)) AS AbsoluteDifference FROM w JOIN Musical_Styles s USING (StyleID);
