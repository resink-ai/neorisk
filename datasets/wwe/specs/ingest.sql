-- WWE: source tables → events (refdata ingest). Matches is 7 scrape copies: each card's matches
-- sit in contiguous id blocks, one per scrape run that saw the card, all identical. The first
-- block holds the distinct matches; the block count gives the card's first run (8 - count).
-- '2023-11-04' is the run-1 time (scrape_run 1): the time of untimed and unused rows.

-- entity: promotions
SELECT CAST(id AS TEXT) AS ext_id, name,
       coalesce((SELECT min(c.event_date) FROM Cards c WHERE c.promotion_id = p.id),
                '2023-11-04') || ' 00:00:00' AS created_at
FROM Promotions p ORDER BY id;

-- entity: locations
SELECT CAST(id AS TEXT) AS ext_id, name,
       coalesce(f.d, '2023-11-04') || ' 00:00:00' AS created_at
FROM Locations l
LEFT JOIN (SELECT location_id, min(event_date) AS d FROM Cards GROUP BY location_id) f
    ON f.location_id = l.id
ORDER BY id;

-- entity: shows
SELECT CAST(id AS TEXT) AS ext_id, name,
       coalesce(f.d, '2023-11-04') || ' 00:00:00' AS created_at
FROM Events e
LEFT JOIN (SELECT event_id, min(event_date) AS d FROM Cards GROUP BY event_id) f
    ON f.event_id = e.id
ORDER BY id;

-- entity: sides
-- Created on the earliest card date of a match that uses the side, as winner or loser.
WITH u AS (SELECT winner_id AS w, card_id FROM Matches
           UNION SELECT loser_id, card_id FROM Matches),
f AS (SELECT CAST(u.w AS INTEGER) AS wid, min(c.event_date) AS d
      FROM u JOIN Cards c ON c.id = u.card_id GROUP BY 1)
SELECT CAST(id AS TEXT) AS ext_id, name, f.d || ' 00:00:00' AS created_at
FROM Wrestlers w JOIN f ON f.wid = w.id ORDER BY id;

-- entity: belts
SELECT CAST(id AS TEXT) AS ext_id, name, f.d || ' 00:00:00' AS created_at
FROM Belts b
JOIN (SELECT CAST(m.title_id AS INTEGER) AS bid, min(c.event_date) AS d
      FROM Matches m JOIN Cards c ON c.id = m.card_id GROUP BY 1) f ON f.bid = b.id
ORDER BY id;

-- entity: match_types
SELECT CAST(id AS TEXT) AS ext_id, name, f.d || ' 00:00:00' AS created_at
FROM Match_Types t
JOIN (SELECT CAST(m.match_type_id AS INTEGER) AS tid, min(c.event_date) AS d
      FROM Matches m JOIN Cards c ON c.id = m.card_id GROUP BY 1) f ON f.tid = t.id
ORDER BY id;

-- entity: listing_pages
-- Run-1 snapshots of the listing pages.
SELECT CAST(id AS TEXT) AS ext_id, html, url, '2023-11-04 00:00:00' AS created_at
FROM Tables ORDER BY id;

-- event: card_held owner=promotion_id ord=card_id
SELECT event_date || ' 00:00:00' AS event_time, CAST(promotion_id AS TEXT) AS promotion_id,
       id AS card_id, CAST(location_id AS TEXT) AS location_id,
       CAST(event_id AS TEXT) AS show_id
FROM Cards ORDER BY id;

-- event: match_held owner=promotion_id ord=card_id
-- Each card's first id block (islands: id - row number is constant inside a block).
WITH isl AS (SELECT m.*, id - row_number() OVER (PARTITION BY card_id ORDER BY id) AS grp
             FROM Matches m),
first AS (SELECT card_id, min(grp) AS grp FROM isl GROUP BY card_id)
SELECT c.event_date || ' 00:00:00' AS event_time, CAST(c.promotion_id AS TEXT) AS promotion_id,
       i.card_id, row_number() OVER (PARTITION BY i.card_id ORDER BY i.id) AS position,
       i.winner_id, i.loser_id, i.win_type, i.match_type_id,
       CASE WHEN i.duration = '' THEN NULL
            ELSE CAST(substr(i.duration, 1, 2) AS INTEGER) * 60
                 + CAST(substr(i.duration, 4, 2) AS INTEGER) END AS duration_s,
       i.title_id, i.title_change
FROM isl i JOIN first f ON f.card_id = i.card_id AND f.grp = i.grp
JOIN Cards c ON c.id = i.card_id
ORDER BY i.card_id, position;

-- event: scrape_run owner=scraper ord=run
-- Run r's time (a rule): the latest card date among the cards first seen in runs 1..r.
-- Card 2475 has no matches; its id is in the run-1 range, so its first run is 1.
WITH isl AS (SELECT card_id, id - row_number() OVER (PARTITION BY card_id ORDER BY id) AS grp
             FROM Matches),
nb AS (SELECT card_id, count(DISTINCT grp) AS n FROM isl GROUP BY card_id),
fr AS (SELECT c.event_date, coalesce(8 - nb.n, 1) AS first_run
       FROM Cards c LEFT JOIN nb ON nb.card_id = c.id),
runs(run) AS (VALUES (1), (2), (3), (4), (5), (6), (7))
SELECT (SELECT max(event_date) FROM fr WHERE fr.first_run <= runs.run) || ' 00:00:00'
           AS event_time, 'all' AS scraper, run
FROM runs ORDER BY run;

-- event: card_page_scraped owner=promotion_id ord=card_id
-- At the time of the card's first run (the scrape_run rule above).
WITH isl AS (SELECT card_id, id - row_number() OVER (PARTITION BY card_id ORDER BY id) AS grp
             FROM Matches),
nb AS (SELECT card_id, count(DISTINCT grp) AS n FROM isl GROUP BY card_id),
fr AS (SELECT c.id, c.event_date, coalesce(8 - nb.n, 1) AS first_run
       FROM Cards c LEFT JOIN nb ON nb.card_id = c.id),
rt AS (SELECT r.first_run AS run, (SELECT max(event_date) FROM fr f WHERE f.first_run <= r.first_run)
                                  AS t
       FROM (SELECT DISTINCT first_run FROM fr) r)
SELECT rt.t || ' 00:00:00' AS event_time, CAST(c.promotion_id AS TEXT) AS promotion_id,
       c.id AS card_id, fr.first_run AS run, CAST(c.table_id AS TEXT) AS table_id, c.url,
       c.info_html, c.match_html
FROM Cards c JOIN fr ON fr.id = c.id JOIN rt ON rt.run = fr.first_run
ORDER BY c.id;
