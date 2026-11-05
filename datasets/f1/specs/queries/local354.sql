-- local354: drivers of the 1950s who, in some season of the decade, drove for the same
-- constructor in their first and their last race of the season, and took part in at least two
-- distinct rounds that season.
-- No gold SQL; written from the question. It reproduces exec_result variant local354_c
-- exactly (104 names; local354_h is the same set as forename, surname). A round driven for
-- two constructors (shared cars) matches when any of its constructors matches.
WITH x AS (
    SELECT ra.year, ra.round, r.driver_id, r.constructor_id
    FROM results r JOIN races ra USING (race_id)
    WHERE ra.year BETWEEN 1950 AND 1959),
s AS (
    SELECT year, driver_id, min(round) AS first_round, max(round) AS last_round,
           count(DISTINCT round) AS rounds
    FROM x GROUP BY year, driver_id)
SELECT DISTINCT d.forename || ' ' || d.surname AS full_name
FROM s JOIN drivers d USING (driver_id)
WHERE s.rounds >= 2
  AND EXISTS (SELECT 1 FROM x f JOIN x l ON l.year = f.year AND l.driver_id = f.driver_id
              AND l.constructor_id = f.constructor_id
              WHERE f.year = s.year AND f.driver_id = s.driver_id
                AND f.round = s.first_round AND l.round = s.last_round)
ORDER BY full_name;
