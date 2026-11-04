-- English word list: events → source table (refdata rebuild, DuckDB). The base words, then one
-- more copy of a word per source_row_duplicated marker.

-- table: word_list
SELECT word AS words FROM words
UNION ALL
SELECT w.word FROM source_row_duplicated d JOIN words w ON w.word_key = d.word_id
WHERE d.src_table = 'word_list';
