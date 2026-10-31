-- local358: users per age band (20s, 30s, 40s, 50s, others) over all 320 mst_users rows, with
-- age = 2016 − birth year. Written from the question (no gold SQL); matches gold CSV _a (the
-- gold depends on the year it was run: _b is 2025).
WITH a AS (SELECT 2016 - CAST(substr(birth_date, 1, 4) AS INT) AS age FROM mst_users)
SELECT sum(age BETWEEN 20 AND 29) AS s20, sum(age BETWEEN 30 AND 39) AS s30,
       sum(age BETWEEN 40 AND 49) AS s40, sum(age BETWEEN 50 AND 59) AS s50,
       sum(age < 20 OR age >= 60) AS others
FROM a;
