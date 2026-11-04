-- English word list: source table → events (refdata ingest). A non-NULL row with an identical
-- copy at a later rowid is a Spider2 duplicate (rows 1-3,701); the rest is the base list, in
-- rowid order. The 2 NULL rows are base rows, not copies of each other. Every time is the rule
-- T0 = 2016-01-01 00:00:00.

-- entity: words
WITH d AS (SELECT rowid AS r, words,
                  words IS NOT NULL AND rowid < max(rowid) OVER (PARTITION BY words) AS dup
           FROM word_list),
     b AS (SELECT r, words, row_number() OVER (ORDER BY r) AS pos FROM d WHERE NOT dup)
SELECT printf('%06d', pos) AS ext_id, words AS word, '2016-01-01 00:00:00' AS created_at
FROM b ORDER BY pos;

-- event: source_row_duplicated owner=word_id ord=src_rowid
WITH d AS (SELECT rowid AS r, words, max(rowid) OVER (PARTITION BY words) AS m,
                  words IS NOT NULL AND rowid < max(rowid) OVER (PARTITION BY words) AS dup
           FROM word_list),
     b AS (SELECT r, row_number() OVER (ORDER BY r) AS pos FROM d WHERE NOT dup)
SELECT '2016-01-01 00:00:00' AS event_time, printf('%06d', b.pos) AS word_id,
       'word_list' AS src_table, d.r AS src_rowid
FROM d JOIN b ON b.r = d.m WHERE d.dup ORDER BY d.r;
