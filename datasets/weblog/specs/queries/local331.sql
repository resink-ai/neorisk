-- local331: top 3 third pages after two consecutive /detail visits (ORDER BY stamp; ties in row order).
-- Written from the question (no gold SQL); matches no gold variant (they disagree with each other); kept as the source-vs-rebuilt check of tie order.
WITH s AS (SELECT session, path, lead(path,1) OVER w p1, lead(path,2) OVER w p2 FROM activity_log WINDOW w AS (PARTITION BY session ORDER BY stamp))
SELECT p2 third_page, count(*) n FROM s WHERE path='/detail' AND p1='/detail' AND p2 IS NOT NULL GROUP BY p2 ORDER BY n DESC, p2 LIMIT 3;
