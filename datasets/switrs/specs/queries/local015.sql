-- local015: motorcyclist fatality rate (fatalities / collisions, %) by helmet use of the parties.
-- Written from the question (no gold SQL); matches gold CSV _c exactly (helmet_used 18 / 3 /
-- 16.67, helmet_not_used 1 / 0 / 0.0). Joins parties on the f64 case_id, so it fails if any
-- case_id bit changes.
WITH p AS (
    SELECT DISTINCT c.case_id, c.motorcyclist_killed_count AS k,
           CASE WHEN p.party_safety_equipment_1 LIKE '%motorcycle helmet used%'
                  OR p.party_safety_equipment_2 LIKE '%motorcycle helmet used%' THEN 'helmet_used'
                WHEN p.party_safety_equipment_1 LIKE '%motorcycle helmet not used%'
                  OR p.party_safety_equipment_2 LIKE '%motorcycle helmet not used%'
                THEN 'helmet_not_used' END AS g
    FROM collisions c JOIN parties p ON p.case_id = c.case_id
    WHERE c.motorcycle_collision = 1)
SELECT g AS helmet_usage_group, count(*) AS collision_count,
       sum(k) AS motorcyclist_fatalities, round(100.0 * sum(k) / count(*), 2) AS fatality_rate_pct
FROM p WHERE g IS NOT NULL GROUP BY g ORDER BY g;
