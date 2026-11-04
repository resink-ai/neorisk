-- name: matches_ref_text_shape
-- Matches' ref columns are TEXT: are they all canonical decimal integers?
SELECT sum(winner_id <> CAST(CAST(winner_id AS INTEGER) AS TEXT)) bad_winner,
       sum(loser_id <> CAST(CAST(loser_id AS INTEGER) AS TEXT)) bad_loser,
       sum(match_type_id <> CAST(CAST(match_type_id AS INTEGER) AS TEXT)) bad_mt,
       sum(title_id <> CAST(CAST(title_id AS INTEGER) AS TEXT)) bad_title
FROM Matches;

-- name: fk_orphans
SELECT 'Matches.card_id' fk, count(*) orphans FROM Matches m WHERE NOT EXISTS (SELECT 1 FROM Cards c WHERE c.id = m.card_id) UNION ALL
SELECT 'Matches.winner_id', count(*) FROM Matches m WHERE NOT EXISTS (SELECT 1 FROM Wrestlers w WHERE w.id = m.winner_id) UNION ALL
SELECT 'Matches.loser_id', count(*) FROM Matches m WHERE NOT EXISTS (SELECT 1 FROM Wrestlers w WHERE w.id = m.loser_id) UNION ALL
SELECT 'Matches.match_type_id', count(*) FROM Matches m WHERE NOT EXISTS (SELECT 1 FROM Match_Types t WHERE t.id = m.match_type_id) UNION ALL
SELECT 'Matches.title_id', count(*) FROM Matches m WHERE NOT EXISTS (SELECT 1 FROM Belts b WHERE b.id = m.title_id) UNION ALL
SELECT 'Cards.table_id', count(*) FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Tables t WHERE t.id = c.table_id) UNION ALL
SELECT 'Cards.location_id', count(*) FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Locations t WHERE t.id = c.location_id) UNION ALL
SELECT 'Cards.promotion_id', count(*) FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Promotions t WHERE t.id = c.promotion_id) UNION ALL
SELECT 'Cards.event_id', count(*) FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Events t WHERE t.id = c.event_id);

-- name: unused_parents
SELECT 'Cards without matches' what, count(*) n FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Matches m WHERE m.card_id = c.id) UNION ALL
SELECT 'Tables without cards', count(*) FROM Tables t WHERE NOT EXISTS (SELECT 1 FROM Cards c WHERE c.table_id = t.id) UNION ALL
SELECT 'Locations unused', count(*) FROM Locations t WHERE NOT EXISTS (SELECT 1 FROM Cards c WHERE c.location_id = t.id) UNION ALL
SELECT 'Events unused', count(*) FROM Events t WHERE NOT EXISTS (SELECT 1 FROM Cards c WHERE c.event_id = t.id) UNION ALL
SELECT 'Promotions unused', count(*) FROM Promotions t WHERE NOT EXISTS (SELECT 1 FROM Cards c WHERE c.promotion_id = t.id) UNION ALL
SELECT 'Wrestlers unused', count(*) FROM Wrestlers w WHERE w.id NOT IN (SELECT CAST(winner_id AS INTEGER) FROM Matches UNION SELECT CAST(loser_id AS INTEGER) FROM Matches) UNION ALL
SELECT 'Belts unused', count(*) FROM Belts b WHERE b.id NOT IN (SELECT CAST(title_id AS INTEGER) FROM Matches) UNION ALL
SELECT 'Match_Types unused', count(*) FROM Match_Types t WHERE t.id NOT IN (SELECT CAST(match_type_id AS INTEGER) FROM Matches);

-- name: fp_card_counter
-- Generator fingerprint: Promotions/Locations/Events/Tables ids are a shared card counter value.
-- id = min(Cards.id) of the cards that use it?
SELECT 'Promotions' t, count(*) n, sum(id = mn) eq, sum(id < mn) lt, sum(id > mn) gt FROM (SELECT p.id, (SELECT min(c.id) FROM Cards c WHERE c.promotion_id = p.id) mn FROM Promotions p) UNION ALL
SELECT 'Locations', count(*), sum(id = mn), sum(id < mn), sum(id > mn) FROM (SELECT p.id, (SELECT min(c.id) FROM Cards c WHERE c.location_id = p.id) mn FROM Locations p) UNION ALL
SELECT 'Events', count(*), sum(id = mn), sum(id < mn), sum(id > mn) FROM (SELECT p.id, (SELECT min(c.id) FROM Cards c WHERE c.event_id = p.id) mn FROM Events p) UNION ALL
SELECT 'Tables', count(*), sum(id = mn), sum(id < mn), sum(id > mn) FROM (SELECT p.id, (SELECT min(c.id) FROM Cards c WHERE c.table_id = p.id) mn FROM Tables p);

-- name: fp_match_counter
-- Belts/Match_Types id = min(Matches.id) using it; Wrestlers id = min(2*id-1 as winner, 2*id as loser).
WITH b AS (SELECT CAST(title_id AS INTEGER) k, min(id) mn FROM Matches GROUP BY 1),
     t AS (SELECT CAST(match_type_id AS INTEGER) k, min(id) mn FROM Matches GROUP BY 1),
     w AS (SELECT k, min(slot) mn FROM (SELECT CAST(winner_id AS INTEGER) k, 2*id-1 slot FROM Matches
                                        UNION ALL SELECT CAST(loser_id AS INTEGER), 2*id FROM Matches) GROUP BY k)
SELECT 'Belts' t, count(*), sum(x.id = mn) eq, sum(x.id < mn), sum(x.id > mn) FROM Belts x JOIN b ON b.k = x.id UNION ALL
SELECT 'Match_Types', count(*), sum(x.id = mn), sum(x.id < mn), sum(x.id > mn) FROM Match_Types x JOIN t ON t.k = x.id UNION ALL
SELECT 'Wrestlers', count(*), sum(x.id = mn), sum(x.id < mn), sum(x.id > mn) FROM Wrestlers x JOIN w ON w.k = x.id;

-- name: fp_card_counter_misses
SELECT 'Tables' t, p.id, (SELECT min(c.id) FROM Cards c WHERE c.table_id = p.id) mn, p.url FROM Tables p
WHERE p.id <> coalesce((SELECT min(c.id) FROM Cards c WHERE c.table_id = p.id), -1) ORDER BY p.id LIMIT 20;

-- name: fp_card_counter_misses_other
SELECT 'Locations' t, p.id, (SELECT min(c.id) FROM Cards c WHERE c.location_id = p.id) mn, p.name FROM Locations p
WHERE p.id <> coalesce((SELECT min(c.id) FROM Cards c WHERE c.location_id = p.id), -1) UNION ALL
SELECT 'Events', p.id, (SELECT min(c.id) FROM Cards c WHERE c.event_id = p.id), p.name FROM Events p
WHERE p.id <> coalesce((SELECT min(c.id) FROM Cards c WHERE c.event_id = p.id), -1) LIMIT 40;

-- name: matches_per_card_order
-- Are each card's matches a contiguous id range, and are cards' match ranges in card id order?
WITH r AS (SELECT card_id, min(id) lo, max(id) hi, count(*) n FROM Matches GROUP BY card_id)
SELECT sum(hi - lo + 1 = n) contiguous, count(*) cards,
       (SELECT count(*) FROM (SELECT card_id, lo, lag(card_id) OVER (ORDER BY lo) pc FROM r) WHERE card_id < pc) card_id_decreasing_steps
FROM r;

-- name: card_gap_vs_tables
-- 14431 counter values, 12639 cards: missing card ids. Where do they sit?
WITH RECURSIVE s(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM s WHERE i < 14431)
SELECT count(*) missing_ids, sum(i > (SELECT max(id) FROM Cards)) after_last_card,
       sum(i IN (SELECT id FROM Tables)) used_by_tables, sum(i IN (SELECT id FROM Locations)) used_by_locations,
       sum(i IN (SELECT id FROM Events)) used_by_events
FROM s WHERE i NOT IN (SELECT id FROM Cards);

-- name: cards_per_table
SELECT n cards_per_table, count(*) tables FROM (SELECT table_id, count(*) n FROM Cards GROUP BY table_id) GROUP BY n ORDER BY n;

-- name: table_id_vs_promo
SELECT p.name, count(DISTINCT c.table_id) tables, count(*) cards, min(c.id), max(c.id), min(event_date), max(event_date)
FROM Cards c JOIN Promotions p ON p.id = c.promotion_id GROUP BY p.name ORDER BY min(c.id);

-- name: table_page_promo_mix
-- Does a listing page (Tables row) hold cards of more than one promotion?
SELECT count(*) FROM (SELECT table_id FROM Cards GROUP BY table_id HAVING count(DISTINCT promotion_id) > 1);

-- name: unique_dups
SELECT (SELECT count(*) - count(DISTINCT name) FROM Wrestlers) wrestler_dup_names,
       (SELECT count(*) - count(DISTINCT lower(name)) FROM Wrestlers) wrestler_dup_lower,
       (SELECT count(*) - count(DISTINCT url) FROM Cards) card_dup_url,
       (SELECT count(*) - count(DISTINCT info_html) FROM Cards) card_dup_info;

-- name: matches_self
SELECT count(*) winner_eq_loser FROM Matches WHERE winner_id = loser_id;
