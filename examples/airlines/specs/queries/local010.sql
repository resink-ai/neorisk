-- local010: unique city pairs bucketed by their average route distance (0, 1000, ..., 6000+);
-- the number of pairs in the emptiest bucket. Written from the question and
-- haversine_formula.md (no gold SQL; the gold value looks unreliable, see the research).
WITH c AS (SELECT airport_code AS code, json_extract(city, '$.en') AS city,
                  CAST(substr(coordinates, 2, instr(coordinates, ',') - 2) AS REAL) AS lon,
                  CAST(substr(coordinates, instr(coordinates, ',') + 1,
                              length(coordinates) - instr(coordinates, ',') - 1) AS REAL) AS lat
           FROM airports_data),
d AS (SELECT MIN(a.city, b.city) AS city1, MAX(a.city, b.city) AS city2,
             2 * 6371 * asin(sqrt(power(sin((radians(b.lat) - radians(a.lat)) / 2), 2)
               + cos(radians(a.lat)) * cos(radians(b.lat))
                 * power(sin((radians(b.lon) - radians(a.lon)) / 2), 2))) AS km
      FROM flights f JOIN c a ON a.code = f.departure_airport
      JOIN c b ON b.code = f.arrival_airport),
p AS (SELECT city1, city2, AVG(km) AS avgkm FROM d GROUP BY 1, 2),
b AS (SELECT MIN(6000, CAST(avgkm / 1000 AS INTEGER) * 1000) AS bucket, COUNT(*) AS pairs
      FROM p GROUP BY 1)
SELECT MIN(pairs) AS fewest_pairs FROM b;
