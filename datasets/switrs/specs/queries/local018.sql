-- local018: for 2021's most common PCF violation category, its share of 2011's collisions minus
-- its share of 2021's, in percentage points. Written from the question (no gold SQL); matches
-- gold CSV _a: speeding, 31.3315% − 31.8852% = −0.553654.
WITH a AS (SELECT substr(collision_date, 1, 4) AS y, count(*) AS tot FROM collisions GROUP BY 1),
     top AS (SELECT pcf_violation_category AS c FROM collisions
             WHERE substr(collision_date, 1, 4) = '2021'
             GROUP BY 1 ORDER BY count(*) DESC LIMIT 1),
     s AS (SELECT substr(collision_date, 1, 4) AS y,
                  100.0 * count(*) / (SELECT tot FROM a WHERE a.y = substr(collision_date, 1, 4))
                      AS share
           FROM collisions
           WHERE pcf_violation_category = (SELECT c FROM top)
             AND substr(collision_date, 1, 4) IN ('2011', '2021')
           GROUP BY 1)
SELECT round(max(CASE WHEN y = '2011' THEN share END)
             - max(CASE WHEN y = '2021' THEN share END), 6) AS share_change
FROM s;
