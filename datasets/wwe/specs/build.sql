-- WWE: events → source tables (refdata rebuild, DuckDB). Ids come back from ext_id; Matches'
-- four ref columns are TEXT in the source, so they come back as VARCHAR.

-- table: Promotions
SELECT CAST(ext_id AS BIGINT) AS id, name FROM promotions;

-- table: Locations
SELECT CAST(ext_id AS BIGINT) AS id, name FROM locations;

-- table: Events
SELECT CAST(ext_id AS BIGINT) AS id, name FROM shows;

-- table: Wrestlers
SELECT CAST(ext_id AS BIGINT) AS id, name FROM sides;

-- table: Belts
SELECT CAST(ext_id AS BIGINT) AS id, name FROM belts;

-- table: Match_Types
SELECT CAST(ext_id AS BIGINT) AS id, name FROM match_types;

-- table: Tables
SELECT CAST(ext_id AS BIGINT) AS id, html, url FROM listing_pages;

-- table: Cards
SELECT h.card_id AS id, CAST(t.ext_id AS BIGINT) AS table_id,
       CAST(l.ext_id AS BIGINT) AS location_id, CAST(p.ext_id AS BIGINT) AS promotion_id,
       strftime(h.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS event_date,
       CAST(s.ext_id AS BIGINT) AS event_id, g.url, g.info_html, g.match_html
FROM card_held h
JOIN card_page_scraped g ON g.card_id = h.card_id
JOIN listing_pages t ON t.page_id = g.table_id
JOIN locations l ON l.location_id = h.location_id
JOIN promotions p ON p.promotion_id = h.promotion_id
JOIN shows s ON s.show_id = h.show_id;

-- table: Matches
-- Run r appends, in card-id order, the distinct matches (in card order) of every card first
-- scraped in a run <= r; id is the running row number.
SELECT row_number() OVER (ORDER BY r.run, m.card_id, m.position) AS id, m.card_id,
       CAST(w.ext_id AS VARCHAR) AS winner_id, m.win_type, CAST(lo.ext_id AS VARCHAR) AS loser_id,
       CAST(mt.ext_id AS VARCHAR) AS match_type_id,
       CASE WHEN m.duration_s IS NULL THEN ''
            ELSE printf('%02d:%02d', m.duration_s // 60, m.duration_s % 60) END AS duration,
       CAST(b.ext_id AS VARCHAR) AS title_id, m.title_change
FROM scrape_run r
JOIN card_page_scraped g ON g.run <= r.run
JOIN match_held m ON m.card_id = g.card_id
JOIN sides w ON w.side_id = m.winner_id
JOIN sides lo ON lo.side_id = m.loser_id
JOIN match_types mt ON mt.match_type_id = m.match_type_id
JOIN belts b ON b.belt_id = m.title_id;
