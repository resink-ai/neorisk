-- name: local019_gold_sql
WITH MatchDetails AS (
    SELECT
        b.name AS titles,
        m.duration AS match_duration,
        w1.name || ' vs ' || w2.name AS matches,
        m.win_type AS win_type,
        l.name AS location,
        e.name AS event,
        ROW_NUMBER() OVER (PARTITION BY b.name ORDER BY m.duration ASC) AS rank
    FROM 
        Belts b
    INNER JOIN Matches m ON m.title_id = b.id
    INNER JOIN Wrestlers w1 ON w1.id = m.winner_id
    INNER JOIN Wrestlers w2 ON w2.id = m.loser_id
    INNER JOIN Cards c ON c.id = m.card_id
    INNER JOIN Locations l ON l.id = c.location_id
    INNER JOIN Events e ON e.id = c.event_id
    INNER JOIN Promotions p ON p.id = c.promotion_id
    WHERE
        p.name = 'NXT'
        AND m.duration <> ''
        AND b.name <> ''
        AND b.name NOT IN (
            SELECT name 
            FROM Belts 
            WHERE name LIKE '%title change%'
        )
),
Rank1 AS (
SELECT 
    titles,
    match_duration,
    matches,
    win_type,
    location,
    event
FROM 
    MatchDetails
WHERE 
    rank = 1
)
SELECT
    SUBSTR(matches, 1, INSTR(matches, ' vs ') - 1) AS wrestler1,
    SUBSTR(matches, INSTR(matches, ' vs ') + 4) AS wrestler2
FROM
Rank1
ORDER BY match_duration 
LIMIT 1;

-- name: local019_shortest_nxt_title_matches
-- The 5 shortest NXT title matches (any belt), to see ties and the _a variant (Stratton/Hail 08:28).
SELECT b.name belt, m.duration, w1.name winner, w2.name loser, m.title_change, count(*) copies, min(m.id)
FROM Matches m JOIN Cards c ON c.id = m.card_id JOIN Promotions p ON p.id = c.promotion_id
JOIN Belts b ON b.id = m.title_id JOIN Wrestlers w1 ON w1.id = m.winner_id JOIN Wrestlers w2 ON w2.id = m.loser_id
WHERE p.name = 'NXT' AND m.duration <> '' AND m.title_id <> '1'
GROUP BY 1, 2, 3, 4, 5 ORDER BY m.duration LIMIT 8;

-- name: local019_variant_a_title_change_excluded
-- Reading "excluding title change" as title_change = 0: shortest NXT title match.
SELECT w1.name winner_name, w2.name loser_name, m.duration
FROM Matches m JOIN Cards c ON c.id = m.card_id JOIN Promotions p ON p.id = c.promotion_id
JOIN Belts b ON b.id = m.title_id JOIN Wrestlers w1 ON w1.id = m.winner_id JOIN Wrestlers w2 ON w2.id = m.loser_id
WHERE p.name = 'NXT' AND m.duration <> '' AND b.name <> '' AND m.title_change = 0 AND b.name LIKE 'NXT%'
ORDER BY m.duration LIMIT 3;

-- name: local019_variant_a_nxt_womens
SELECT b.name, w1.name winner_name, w2.name loser_name, m.duration, m.title_change
FROM Matches m JOIN Cards c ON c.id = m.card_id JOIN Promotions p ON p.id = c.promotion_id
JOIN Belts b ON b.id = m.title_id JOIN Wrestlers w1 ON w1.id = m.winner_id JOIN Wrestlers w2 ON w2.id = m.loser_id
WHERE w1.name = 'Tiffany Stratton' AND w2.name = 'Thea Hail' GROUP BY 1, 2, 3, 4, 5;

-- name: local019_dedup_invariance
-- Does the gold answer change if Matches is reduced to its first copy (min id per card position)? Shortest per belt over distinct rows:
SELECT count(*) nxt_title_rows, count(DISTINCT m.card_id || '|' || m.winner_id || '|' || m.loser_id || '|' || m.duration || '|' || m.title_id) distinct_rows
FROM Matches m JOIN Cards c ON c.id = m.card_id WHERE c.promotion_id = 10963 AND m.title_id <> '1' AND m.duration <> '';

-- name: local019_variant_a_try_belts_never_changed
-- Try: exclude belts that ever changed hands on NXT; shortest remaining NXT title match.
SELECT b.name, w1.name, w2.name, m.duration FROM Matches m JOIN Cards c ON c.id = m.card_id
JOIN Belts b ON b.id = m.title_id JOIN Wrestlers w1 ON w1.id = m.winner_id JOIN Wrestlers w2 ON w2.id = m.loser_id
WHERE c.promotion_id = 10963 AND m.duration <> '' AND m.title_id <> '1'
  AND m.title_id NOT IN (SELECT title_id FROM Matches m2 JOIN Cards c2 ON c2.id = m2.card_id WHERE c2.promotion_id = 10963 AND m2.title_change = 1)
GROUP BY 1, 2, 3, 4 ORDER BY m.duration LIMIT 5;

-- name: local019_variant_a_try_per_belt_max_of_min
-- Try: per NXT belt the shortest match, listed (to see whether 08:28 is some belt's minimum).
SELECT b.name, min(m.duration) FROM Matches m JOIN Cards c ON c.id = m.card_id JOIN Belts b ON b.id = m.title_id
WHERE c.promotion_id = 10963 AND m.duration <> '' AND m.title_id <> '1' AND m.title_change = 0 GROUP BY 1 ORDER BY 2;
