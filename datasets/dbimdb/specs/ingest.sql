-- dbimdb: source tables → events (refdata ingest).
-- Times are rules (docs/research/spider2/dbimdb.md §2): a movie and its credits at Jan 1 of
-- substr(year, -4); a person or lookup row at its first movie's release; the rating snapshot
-- at N = 2019-01-01. The five 1-per-movie link tables are movie attributes, joined by MID.

-- entity: genres
SELECT CAST(g.GID AS TEXT) AS ext_id, g.Name AS name,
       (SELECT min(substr(m.year, -4)) FROM M_Genre x JOIN Movie m USING (MID)
        WHERE x.GID = g.GID) || '-01-01 00:00:00' AS created_at
FROM Genre g ORDER BY g.GID;

-- entity: languages
SELECT CAST(l.LAID AS TEXT) AS ext_id, l.Name AS name,
       (SELECT min(substr(m.year, -4)) FROM M_Language x JOIN Movie m USING (MID)
        WHERE x.LAID = l.LAID) || '-01-01 00:00:00' AS created_at
FROM Language l ORDER BY l.LAID;

-- entity: countries
SELECT CAST(c.CID AS TEXT) AS ext_id, c.Name AS name,
       (SELECT min(substr(m.year, -4)) FROM M_Country x JOIN Movie m USING (MID)
        WHERE x.CID = c.CID) || '-01-01 00:00:00' AS created_at
FROM Country c ORDER BY c.CID;

-- entity: locations
SELECT CAST(l.LID AS TEXT) AS ext_id, l.Name AS name,
       (SELECT min(substr(m.year, -4)) FROM M_Location x JOIN Movie m USING (MID)
        WHERE x.LID = l.LID) || '-01-01 00:00:00' AS created_at
FROM Location l ORDER BY l.LID;

-- entity: persons
-- One row per distinct PID. The name loses the leading space the cast and producer copies
-- carry; the 719 people listed twice have the same name either way, and the same gender.
WITH credit AS (
    SELECT trim(PID) AS pid, MID FROM M_Cast WHERE PID IS NOT NULL
    UNION ALL SELECT trim(PID), MID FROM M_Producer WHERE PID IS NOT NULL
    UNION ALL SELECT PID, MID FROM M_Director),
first AS (SELECT c.pid, min(substr(m.year, -4)) AS y FROM credit c JOIN Movie m USING (MID)
          GROUP BY c.pid)
SELECT p.PID AS ext_id,
       max(CASE WHEN substr(p.Name, 1, 1) = ' ' THEN substr(p.Name, 2) ELSE p.Name END) AS name,
       max(p.Gender) AS gender, f.y || '-01-01 00:00:00' AS created_at
FROM Person p JOIN first f ON f.pid = p.PID
GROUP BY p.PID ORDER BY p.PID;

-- entity: movies
SELECT m.MID AS ext_id, m."index" AS src_index, m.title AS title,
       CASE WHEN length(m.year) > 4 THEN substr(m.year, 1, length(m.year) - 5) END AS disambig,
       substr(m.year, -4) || '-01-01 00:00:00' AS created_at,
       g.GID AS genre_id, la.LAID AS language_id, CAST(c.CID AS INTEGER) AS country_id,
       CAST(lo.LID AS INTEGER) AS location_id, d.PID AS director_id
FROM Movie m JOIN M_Genre g USING (MID) JOIN M_Language la USING (MID)
JOIN M_Country c USING (MID) JOIN M_Location lo USING (MID) JOIN M_Director d USING (MID)
ORDER BY m."index";

-- event: cast_credited owner=movie_id ord=billing
SELECT substr(m.year, -4) || '-01-01 00:00:00' AS event_time, c.MID AS movie_id,
       trim(c.PID) AS person_id,
       row_number() OVER (PARTITION BY c.MID ORDER BY c."index") AS billing
FROM M_Cast c JOIN Movie m USING (MID) ORDER BY c."index";

-- event: producer_credited owner=movie_id ord=position
SELECT substr(m.year, -4) || '-01-01 00:00:00' AS event_time, p.MID AS movie_id,
       trim(p.PID) AS person_id,
       row_number() OVER (PARTITION BY p.MID ORDER BY p."index") AS position
FROM M_Producer p JOIN Movie m USING (MID) ORDER BY p."index";

-- event: movies_snapshot owner=movie_id
SELECT '2019-01-01 00:00:00' AS event_time, MID AS movie_id, rating, num_votes
FROM Movie ORDER BY "index";
