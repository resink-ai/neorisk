-- local041: the percentage of Bronx trees whose health is 'Good'.
-- Written from the question (no gold SQL); both gold variants in one row:
--   pct_a = gold CSV _a (78.1473): Good / all Bronx rows, over raw rows (injected copies included);
--   pct_b = gold CSV _b (82.649376): Good / Bronx rows with non-NULL health, over distinct trees.
SELECT (SELECT 100.0 * sum(health = 'Good') / count(*) FROM trees WHERE boroname = 'Bronx') AS pct_a,
       (SELECT 100.0 * sum(health = 'Good') / count(health)
        FROM (SELECT DISTINCT * FROM trees) WHERE boroname = 'Bronx') AS pct_b;
