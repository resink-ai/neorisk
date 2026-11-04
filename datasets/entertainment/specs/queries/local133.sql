-- local133: a weighted score per ranked style (3, 2 and 1 points for a 1st, 2nd and 3rd
-- preference), and each style's absolute difference from the mean score over the 20 styles.
-- Written from the question (no gold SQL). Reproduces gold variant local133_a.csv, 20 of 20
-- rows (local133_b.csv has the same differences plus the score and mean columns).
WITH w AS (SELECT StyleID,
                  sum(CASE PreferenceSeq WHEN 1 THEN 3 WHEN 2 THEN 2 WHEN 3 THEN 1 END) AS score
           FROM Musical_Preferences GROUP BY 1)
SELECT s.StyleName, abs(score - (SELECT avg(score) FROM w)) AS AbsoluteDifference
FROM w JOIN Musical_Styles s USING (StyleID);
