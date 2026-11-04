-- name: matches_rebuild_sql
-- The build.sql rule, in SQL: distinct matches (each card's first block, with its position) plus each
-- card's first scrape run regenerate Matches exactly. Islands = runs of consecutive ids per card.
WITH isl AS (SELECT m.*, id - row_number() OVER (PARTITION BY card_id ORDER BY id) grp FROM Matches m),
blk AS (SELECT isl.*, dense_rank() OVER (PARTITION BY card_id ORDER BY grp) b FROM isl),
card_run AS (SELECT card_id, 8 - max(b) first_run FROM blk GROUP BY card_id),
dm AS (SELECT card_id, row_number() OVER (PARTITION BY card_id ORDER BY id) pos, winner_id, win_type, loser_id,
              match_type_id, duration, title_id, title_change FROM blk WHERE b = 1),
runs(r) AS (VALUES (1), (2), (3), (4), (5), (6), (7)),
reb AS (SELECT row_number() OVER (ORDER BY runs.r, dm.card_id, dm.pos) id, dm.card_id, winner_id, win_type, loser_id,
               match_type_id, duration, title_id, title_change
        FROM runs JOIN card_run cr ON cr.first_run <= runs.r JOIN dm ON dm.card_id = cr.card_id)
SELECT (SELECT count(*) FROM dm) distinct_matches, (SELECT count(*) FROM reb) rebuilt,
       (SELECT count(*) FROM (SELECT * FROM reb EXCEPT SELECT * FROM Matches)) only_rebuilt,
       (SELECT count(*) FROM (SELECT * FROM Matches EXCEPT SELECT * FROM reb)) only_source;

-- name: duration_seconds_roundtrip
-- duration as opt(i64) seconds ('' -> NULL) and back.
SELECT count(*) n, sum(back IS NOT duration) differ FROM (
  SELECT duration, CASE WHEN s IS NULL THEN '' ELSE printf('%02d:%02d', s / 60, s % 60) END back
  FROM (SELECT duration, CASE WHEN duration = '' THEN NULL ELSE CAST(substr(duration, 1, 2) AS INTEGER) * 60 + CAST(substr(duration, 4, 2) AS INTEGER) END s FROM Matches));

-- name: ref_text_roundtrip
-- ref columns stored as TEXT must come back as TEXT of the integer id.
SELECT sum(typeof(winner_id) <> 'text') + sum(typeof(loser_id) <> 'text') + sum(typeof(match_type_id) <> 'text') + sum(typeof(title_id) <> 'text') non_text,
       sum(CAST(CAST(winner_id AS INTEGER) AS TEXT) <> winner_id) differ
FROM Matches;

-- name: wrestler_first_use_date
-- Entity created_at by rule: the earliest card date that uses it. Wrestlers whose first use by id (the
-- counter slot) is not on their earliest date: id order is listing order (newest first), not time order.
WITH u AS (SELECT CAST(winner_id AS INTEGER) w, card_id FROM Matches UNION ALL SELECT CAST(loser_id AS INTEGER), card_id FROM Matches),
f AS (SELECT w, min(c.event_date) d FROM u JOIN Cards c ON c.id = u.card_id GROUP BY w)
SELECT count(*) wrestlers, min(d), max(d), sum(d >= '2023-11-05') first_seen_after_run1 FROM f;

-- name: snapshot_N
SELECT max(event_date) N, min(event_date) start FROM Cards;
