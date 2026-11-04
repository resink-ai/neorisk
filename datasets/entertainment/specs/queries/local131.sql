-- local131: per musical style, how often it is a customer's 1st, 2nd and 3rd preference, in
-- one row per style.
-- Written from the question, after the gold SQL. The gold SQL's inner join and HAVING drop
-- the 5 styles nobody prefers (20 rows), so it does not equal its own CSV; this LEFT JOIN form
-- reproduces gold variant local131_a.csv, 25 of 25 rows, zeros included.
SELECT s.StyleID, s.StyleName,
       count(CASE WHEN p.PreferenceSeq = 1 THEN 1 END) AS FirstPreferenceCount,
       count(CASE WHEN p.PreferenceSeq = 2 THEN 1 END) AS SecondPreferenceCount,
       count(CASE WHEN p.PreferenceSeq = 3 THEN 1 END) AS ThirdPreferenceCount
FROM Musical_Styles s LEFT JOIN Musical_Preferences p USING (StyleID)
GROUP BY s.StyleID, s.StyleName;
