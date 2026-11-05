-- name: row_counts
SELECT 'Promotions' t, count(*) n, min(id), max(id) FROM Promotions UNION ALL
SELECT 'Tables', count(*), min(id), max(id) FROM Tables UNION ALL
SELECT 'Cards', count(*), min(id), max(id) FROM Cards UNION ALL
SELECT 'Locations', count(*), min(id), max(id) FROM Locations UNION ALL
SELECT 'Events', count(*), min(id), max(id) FROM Events UNION ALL
SELECT 'Matches', count(*), min(id), max(id) FROM Matches UNION ALL
SELECT 'Belts', count(*), min(id), max(id) FROM Belts UNION ALL
SELECT 'Wrestlers', count(*), min(id), max(id) FROM Wrestlers UNION ALL
SELECT 'Match_Types', count(*), min(id), max(id) FROM Match_Types;

-- name: sqlite_sequence
SELECT * FROM sqlite_sequence;

-- name: text_bytes
SELECT 'Tables.html' col, sum(length(CAST(html AS BLOB))) bytes, max(length(html)) maxlen FROM Tables UNION ALL
SELECT 'Cards.info_html', sum(length(CAST(info_html AS BLOB))), max(length(info_html)) FROM Cards UNION ALL
SELECT 'Cards.match_html', sum(length(CAST(match_html AS BLOB))), max(length(match_html)) FROM Cards UNION ALL
SELECT 'Cards.url', sum(length(CAST(url AS BLOB))), max(length(url)) FROM Cards;

-- name: typeof_cards
SELECT typeof(table_id), typeof(location_id), typeof(promotion_id), typeof(event_date), typeof(event_id),
       typeof(url), typeof(info_html), typeof(match_html), count(*) FROM Cards GROUP BY 1,2,3,4,5,6,7,8;

-- name: typeof_matches
SELECT typeof(card_id), typeof(winner_id), typeof(win_type), typeof(loser_id), typeof(match_type_id),
       typeof(duration), typeof(title_id), typeof(title_change), count(*) FROM Matches GROUP BY 1,2,3,4,5,6,7,8;

-- name: typeof_lookups
SELECT 'Promotions', typeof(name), count(*) FROM Promotions GROUP BY 2 UNION ALL
SELECT 'Locations', typeof(name), count(*) FROM Locations GROUP BY 2 UNION ALL
SELECT 'Events', typeof(name), count(*) FROM Events GROUP BY 2 UNION ALL
SELECT 'Belts', typeof(name), count(*) FROM Belts GROUP BY 2 UNION ALL
SELECT 'Wrestlers', typeof(name), count(*) FROM Wrestlers GROUP BY 2 UNION ALL
SELECT 'Match_Types', typeof(name), count(*) FROM Match_Types GROUP BY 2 UNION ALL
SELECT 'Tables.html', typeof(html), count(*) FROM Tables GROUP BY 2 UNION ALL
SELECT 'Tables.url', typeof(url), count(*) FROM Tables GROUP BY 2;

-- name: empty_names
SELECT 'Promotions' t, id, quote(name) FROM Promotions WHERE name IS NULL OR name = '' OR name <> trim(name) UNION ALL
SELECT 'Locations', id, quote(name) FROM Locations WHERE name IS NULL OR name = '' OR name <> trim(name) UNION ALL
SELECT 'Events', id, quote(name) FROM Events WHERE name IS NULL OR name = '' OR name <> trim(name) UNION ALL
SELECT 'Belts', id, quote(name) FROM Belts WHERE name IS NULL OR name = '' OR name <> trim(name) UNION ALL
SELECT 'Wrestlers', id, quote(name) FROM Wrestlers WHERE name IS NULL OR name = '' OR name <> trim(name) UNION ALL
SELECT 'Match_Types', id, quote(name) FROM Match_Types WHERE name IS NULL OR name = '' OR name <> trim(name);

-- name: nulls_cards
SELECT sum(table_id IS NULL), sum(location_id IS NULL), sum(promotion_id IS NULL), sum(event_date IS NULL),
       sum(event_date = ''), sum(event_id IS NULL), sum(url IS NULL), sum(info_html IS NULL), sum(match_html IS NULL)
FROM Cards;

-- name: nulls_matches
SELECT sum(card_id IS NULL), sum(winner_id IS NULL), sum(winner_id=''), sum(win_type IS NULL), sum(win_type=''),
       sum(loser_id IS NULL), sum(loser_id=''), sum(match_type_id IS NULL), sum(match_type_id=''),
       sum(duration IS NULL), sum(duration=''), sum(title_id IS NULL), sum(title_id=''), sum(title_change IS NULL)
FROM Matches;

-- name: matches_id_dense
SELECT count(*) n, max(id) - min(id) + 1 span FROM Matches;

-- name: cards_id_gaps
SELECT count(*) n, max(id) span, (SELECT count(*) FROM Cards c WHERE NOT EXISTS (SELECT 1 FROM Cards d WHERE d.id = c.id + 1)) - 1 gaps FROM Cards;

-- name: tables_id_pattern
SELECT id % 10 AS id_mod_10, count(*) FROM Tables GROUP BY 1;

-- name: tables_url_promo
SELECT substr(url, 37, instr(substr(url, 37), '-cards') - 1) promo, count(*), min(id), max(id) FROM Tables GROUP BY 1 ORDER BY min(id);

-- name: tables_url_shape
SELECT url FROM Tables WHERE id IN (1, 11, (SELECT max(id) FROM Tables)) ORDER BY id;

-- name: tables_vs_card_ids
SELECT count(*) tables_with_card_same_id, (SELECT count(*) FROM Tables) n_tables
FROM Tables t JOIN Cards c ON c.id = t.id AND c.table_id = t.id;
