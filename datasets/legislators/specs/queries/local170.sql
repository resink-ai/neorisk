-- local170: states (of the first term) where both male and female legislators keep retention
-- above zero at 0, 2, 4, 6, 8 and 10 years after their first term start (serving on Dec 31).
-- No gold SQL; written from the question (docs/research/spider2/legislators.md §0.1,
-- scripts/legislators/q2_gold.sql local170_with_date_dim). Reproduces gold _b (23 states): the
-- Dec 31 rows of legislation_date_dim. Gold _a (34 states) uses every Dec 31 instead.
WITH f AS (SELECT t.id_bioguide, l.gender, t.term_start AS fs, t.state
           FROM legislators_terms t JOIN legislators l USING (id_bioguide)
           WHERE t.term_number = 0),
r AS (SELECT DISTINCT f.state, f.gender,
             CAST(strftime('%Y', d.date) AS INTEGER) - CAST(strftime('%Y', f.fs) AS INTEGER) AS n
      FROM f JOIN legislators_terms t USING (id_bioguide)
      JOIN legislation_date_dim d ON d.date BETWEEN t.term_start AND t.term_end
           AND d.month_name = 'December' AND d.day_of_month = 31),
ok AS (SELECT state, gender FROM r WHERE n IN (0, 2, 4, 6, 8, 10)
       GROUP BY 1, 2 HAVING count(DISTINCT n) = 6)
SELECT state FROM ok GROUP BY state HAVING count(*) = 2 ORDER BY state;
