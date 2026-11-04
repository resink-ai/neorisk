-- local009: the longest route (haversine, km) with Abakan as departure or arrival city.
-- Written from the question and haversine_formula.md (no gold SQL); reproduces the gold
-- value 3484.15 km (research: scripts/airlines/q6_ids.sql).
WITH c AS (SELECT airport_code AS code, json_extract(city, '$.en') AS city,
                  CAST(substr(coordinates, 2, instr(coordinates, ',') - 2) AS REAL) AS lon,
                  CAST(substr(coordinates, instr(coordinates, ',') + 1,
                              length(coordinates) - instr(coordinates, ',') - 1) AS REAL) AS lat
           FROM airports_data)
SELECT ROUND(MAX(2 * 6371 * asin(sqrt(power(sin((radians(b.lat) - radians(a.lat)) / 2), 2)
             + cos(radians(a.lat)) * cos(radians(b.lat))
               * power(sin((radians(b.lon) - radians(a.lon)) / 2), 2)))), 2) AS km
FROM flights f JOIN c a ON a.code = f.departure_airport JOIN c b ON b.code = f.arrival_airport
WHERE a.city = 'Abakan' OR b.city = 'Abakan';
