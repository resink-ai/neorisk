-- local035: geolocation sorted by state, city, zip, lat, lng; the consecutive pair of rows
-- with the largest spherical-law-of-cosines distance. Written from the question (no gold
-- SQL); E_commerce names. Rows are tied on all five sort keys only when identical.
WITH g AS (SELECT geolocation_city AS city, geolocation_state AS state,
                  radians(geolocation_lat) AS la, radians(geolocation_lng) AS lo,
                  LAG(geolocation_city) OVER w AS pcity, LAG(geolocation_state) OVER w AS pstate,
                  LAG(radians(geolocation_lat)) OVER w AS pla,
                  LAG(radians(geolocation_lng)) OVER w AS plo
           FROM geolocation
           WINDOW w AS (ORDER BY geolocation_state, geolocation_city,
                        geolocation_zip_code_prefix, geolocation_lat, geolocation_lng))
SELECT pcity, pstate, city, state,
       ROUND(6371 * acos(MIN(1, MAX(-1, sin(pla) * sin(la) + cos(pla) * cos(la) * cos(lo - plo)))),
             6) AS km
FROM g WHERE pla IS NOT NULL ORDER BY km DESC, pstate, pcity, state, city LIMIT 1;
