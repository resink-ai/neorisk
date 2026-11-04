-- name: event_date_format
SELECT length(event_date) len, event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' iso, count(*),
       sum(date(event_date) IS NULL) invalid, sum(date(event_date) <> event_date) noncanonical, min(event_date), max(event_date)
FROM Cards GROUP BY 1, 2;

-- name: card_id_vs_date_within_promo
-- Listing pages are newest first: card ids should run backwards in date inside a promotion.
SELECT p.name, sum(nxt < event_date) date_desc_steps, sum(nxt > event_date) date_asc_steps, sum(nxt = event_date) same_day
FROM (SELECT promotion_id, event_date, lead(event_date) OVER (PARTITION BY promotion_id ORDER BY id) nxt FROM Cards WHERE id < 13382) c
JOIN Promotions p ON p.id = c.promotion_id WHERE nxt IS NOT NULL GROUP BY p.name;

-- name: late_batches
-- The 91 late cards (ids >= 13382): their id ranges, promotions and dates, by first scrape run (p1).
SELECT CASE WHEN c.id < 13382 THEN 'regular' ELSE 'late' END grp, p.name, count(*), min(c.id), max(c.id), min(event_date), max(event_date)
FROM Cards c JOIN Promotions p ON p.id = c.promotion_id GROUP BY 1, 2 ORDER BY 1 DESC, 2;

-- name: regular_max_date_by_promo
SELECT p.name, max(event_date) FROM Cards c JOIN Promotions p ON p.id = c.promotion_id WHERE c.id < 13382 GROUP BY 1;

-- name: card_without_matches
SELECT id, table_id, promotion_id, event_date, event_id, url, length(match_html) FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Matches m WHERE m.card_id = c.id);

-- name: same_date_cards
SELECT n cards_on_same_date_and_promo, count(*) FROM (SELECT promotion_id, event_date, count(*) n FROM Cards GROUP BY 1, 2) GROUP BY 1;

-- name: events_reuse
SELECT n cards_per_event_name, count(*) events FROM (SELECT event_id, count(*) n FROM Cards GROUP BY 1) GROUP BY 1 ORDER BY 1 LIMIT 20;

-- name: events_top
SELECT e.name, count(*) FROM Cards c JOIN Events e ON e.id = c.event_id GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

-- name: locations_top
SELECT l.name, count(*) FROM Cards c JOIN Locations l ON l.id = c.location_id GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

-- name: win_type_mix
-- Over distinct matches: first copy only (min id per (card, position)) is approximated by the first block, ids < 76998 plus late first blocks; use all rows / copies instead.
SELECT quote(win_type) wt, count(*) rows FROM Matches GROUP BY 1 ORDER BY 2 DESC LIMIT 30;

-- name: duration_format
SELECT CASE WHEN duration = '' THEN 'empty'
            WHEN duration GLOB '[0-9][0-9]:[0-9][0-9]' THEN 'MM:SS'
            WHEN duration GLOB '[0-9]:[0-9][0-9]' THEN 'M:SS'
            WHEN duration GLOB '[0-9][0-9][0-9]:[0-9][0-9]' THEN 'MMM:SS'
            WHEN duration GLOB '[0-9]*:[0-9][0-9]:[0-9][0-9]' THEN 'H:MM:SS'
            ELSE 'other' END shape, count(*), min(duration), max(duration)
FROM Matches GROUP BY 1;

-- name: duration_other
SELECT quote(duration), count(*) FROM Matches WHERE duration <> '' AND NOT duration GLOB '[0-9][0-9]:[0-9][0-9]' GROUP BY 1 ORDER BY 2 DESC LIMIT 20;

-- name: duration_seconds_range
SELECT min(s), max(s), sum(CAST(substr(duration, 4, 2) AS INTEGER) >= 60) bad_seconds
FROM (SELECT duration, CAST(substr(duration, 1, 2) AS INTEGER) * 60 + CAST(substr(duration, 4, 2) AS INTEGER) s FROM Matches WHERE duration GLOB '[0-9][0-9]:[0-9][0-9]');

-- name: title_change_mix
SELECT title_change, title_id = '1' no_title, count(*) FROM Matches GROUP BY 1, 2;

-- name: belts_title_change_names
SELECT id, name FROM Belts WHERE name LIKE '%title change%' OR name LIKE '%change%';

-- name: belts_sample
SELECT id, name FROM Belts ORDER BY id LIMIT 12;

-- name: match_types_top
SELECT quote(t.name), count(*) FROM Matches m JOIN Match_Types t ON t.id = m.match_type_id GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

-- name: winner_eq_loser
SELECT w.id, quote(w.name), win_type, count(*) FROM Matches m JOIN Wrestlers w ON w.id = m.winner_id WHERE winner_id = loser_id GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 10;

-- name: empty_wrestler_use
SELECT sum(winner_id = '4631') as_winner, sum(loser_id = '4631') as_loser FROM Matches;

-- name: wrestler_names_tags
-- Wrestler "names" are participant strings; teams and multi-man sides are one string.
SELECT sum(name LIKE '% & %') amp, sum(name LIKE '%,%') comma, sum(name LIKE '%(%') paren, count(*) FROM Wrestlers;

-- name: wrestler_names_long
SELECT id, name FROM Wrestlers ORDER BY length(name) DESC LIMIT 5;

-- name: promotion_by_belt_prefix
SELECT p.name promo, sum(b.name LIKE 'NXT%') nxt_belts, count(*) FROM Matches m JOIN Cards c ON c.id = m.card_id
JOIN Promotions p ON p.id = c.promotion_id JOIN Belts b ON b.id = m.title_id WHERE m.title_id <> '1' GROUP BY 1;
