-- local167: the state (of the first term) with the most female legislators whose terms cover a
-- December 31, and that count.
-- No gold SQL; written from the question (docs/research/spider2/legislators.md §0.1,
-- scripts/legislators/q2_gold.sql local167_with_date_dim). Reproduces gold _b (CA, 25): the
-- Dec 31 rows of legislation_date_dim. Gold _a (CA, 42) counts every Dec 31 instead.
WITH f AS (SELECT t.id_bioguide, t.state FROM legislators_terms t
           JOIN legislators l USING (id_bioguide)
           WHERE l.gender = 'F' AND t.term_number = 0),
cov AS (SELECT DISTINCT t.id_bioguide FROM legislators_terms t
        JOIN legislators l USING (id_bioguide)
        JOIN legislation_date_dim d ON d.date BETWEEN t.term_start AND t.term_end
             AND d.month_name = 'December' AND d.day_of_month = 31
        WHERE l.gender = 'F')
SELECT f.state, count(*) AS female_legislators_with_dec31_count
FROM f JOIN cov USING (id_bioguide)
GROUP BY f.state
ORDER BY 2 DESC, f.state
LIMIT 1;
