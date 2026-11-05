-- local355: the overall average first and last missed round, over drivers who missed fewer
-- than three races in a year and drove for a different constructor before and after the gap.
-- No gold SQL; written from the question, over the drives table: a gap row (drive_id -1)
-- spans the rounds missed between two drives of a season; gaps of 1 or 2 rounds count, and
-- min() picks one constructor where a shared drive gives two. It matches none of the five
-- exec_result variants; the nearest, local355_a (6.771429, 7.123810, 105 gaps), differs by
-- one gap (this gives 104 gaps: 6.778846, 7.134615).
WITH g AS (
    SELECT d.year, d.driver_id, d.first_round, d.last_round,
           (SELECT min(b.constructor_id) FROM drives b
            WHERE b.year = d.year AND b.driver_id = d.driver_id AND b.drive_id != -1
              AND b.last_round = d.first_round - 1) AS before_c,
           (SELECT min(a.constructor_id) FROM drives a
            WHERE a.year = d.year AND a.driver_id = d.driver_id AND a.drive_id != -1
              AND a.first_round = d.last_round + 1) AS after_c
    FROM drives d WHERE d.drive_id = -1)
SELECT avg(first_round) AS avg_first_missed_round, avg(last_round) AS avg_last_missed_round
FROM g
WHERE last_round - first_round + 1 < 3 AND before_c != after_c;
