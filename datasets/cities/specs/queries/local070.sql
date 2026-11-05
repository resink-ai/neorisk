-- local070: Chinese cities in July 2021: the dates of the shortest and longest streaks of
-- consecutive insert dates, one city per date, the name capitalised, ordered by date.
-- No gold SQL (gold is local070_a.csv and _b.csv). Written from the question; reproduces
-- variant _a, whose city per date is the lowest city_id. _b's picks follow no id order.
WITH d AS (
    SELECT DISTINCT insert_date AS dt
    FROM cities
    WHERE country_code_2 = 'cn' AND insert_date BETWEEN '2021-07-01' AND '2021-07-31'
),
i AS (SELECT dt, julianday(dt) - row_number() OVER (ORDER BY dt) AS grp FROM d),
s AS (SELECT grp, count(*) AS len FROM i GROUP BY grp),
picked AS (
    SELECT i.dt FROM i JOIN s USING (grp)
    WHERE s.len IN ((SELECT min(len) FROM s), (SELECT max(len) FROM s))
)
SELECT p.dt AS most_consecutive_dates,
       (SELECT upper(substr(c.city_name, 1, 1)) || lower(substr(c.city_name, 2))
        FROM cities c
        WHERE c.country_code_2 = 'cn' AND c.insert_date = p.dt
        ORDER BY c.city_id LIMIT 1) AS city_name
FROM picked p
ORDER BY p.dt;
