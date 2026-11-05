-- local202: of the top 10 states by alien population, how many have more friendly (aggressive = 0)
-- than hostile aliens and an average age above 200?
-- No gold SQL (gold is local202_a.csv, 5). Written from the question; reproduces variant _a.
WITH s AS (
    SELECT state, count(*) AS n, avg(aggressive = 0) AS friendly, avg(aggressive = 1) AS hostile,
           avg(age) AS avg_age
    FROM alien_data
    GROUP BY state
    ORDER BY n DESC
    LIMIT 10
)
SELECT count(*) AS qualified_states_count
FROM s
WHERE friendly > hostile AND avg_age > 200;
