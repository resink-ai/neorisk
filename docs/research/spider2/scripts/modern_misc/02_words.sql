-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/modern_misc/02_words.sql
.headers on
.mode list
.print ## duplicate block: are rows 1..3702 all words that recur later?
SELECT count(*) rows_1_3702, sum(words IN (SELECT words FROM word_list WHERE rowid>3702)) recur_later, sum(words IS NULL) nulls FROM word_list WHERE rowid<=3702;
SELECT count(*) rows_after, count(DISTINCT words) distinct_after, count(words) nonnull_after FROM word_list WHERE rowid>3702;
.print ## duplicates entirely within rows 3703.. (should be 0 if the base list is a set)
SELECT count(*) FROM (SELECT words FROM word_list WHERE rowid>3702 GROUP BY words HAVING count(*)>1);
.print ## the duplicate word whose first copy is deep in the table
SELECT words, group_concat(rowid, ' ') FROM word_list WHERE words IN (SELECT words FROM word_list GROUP BY words HAVING count(*)>1) AND words IN (SELECT words FROM word_list WHERE rowid>3702 GROUP BY words HAVING count(*)>1) GROUP BY 1;
.print ## NULL words: where, and are the words 'null' / 'nan' / 'na' / 'none' present?
SELECT rowid, words, (SELECT words FROM word_list w WHERE w.rowid=word_list.rowid-1) prev, (SELECT words FROM word_list w WHERE w.rowid=word_list.rowid+1) next FROM word_list WHERE words IS NULL;
SELECT w, (SELECT count(*) FROM word_list WHERE words=w) n FROM (SELECT 'null' w UNION ALL SELECT 'nan' UNION ALL SELECT 'na' UNION ALL SELECT 'none' UNION ALL SELECT 'nul' UNION ALL SELECT 'nana' UNION ALL SELECT 'true' UNION ALL SELECT 'false');
.print ## words with an upper-case letter
SELECT rowid, words FROM word_list WHERE words GLOB '*[A-Z]*';
.print ## descents in the base block (rows 3703..): count, and samples
SELECT sum(b.words<a.words) desc_ FROM word_list a JOIN word_list b ON b.rowid=a.rowid+1 WHERE a.rowid>=3703 AND a.words IS NOT NULL AND b.words IS NOT NULL;
SELECT a.rowid, a.words, b.words FROM word_list a JOIN word_list b ON b.rowid=a.rowid+1 WHERE a.rowid>=3703 AND b.words<a.words LIMIT 8;
.print ## is the base block sorted by a different collation? descents when comparing lower(), and by (length) no
SELECT sum(lower(b.words)<lower(a.words)) desc_lower FROM word_list a JOIN word_list b ON b.rowid=a.rowid+1 WHERE a.rowid>=3703;
.print ## corrected block boundary: rows 1..3701 are the prepended copies (3701 = round(1% of 370103))
SELECT count(*) rows_1_3701, sum(words IN (SELECT words FROM word_list WHERE rowid>3701)) recur_later FROM word_list WHERE rowid<=3701;
SELECT count(*) base_rows, count(DISTINCT words) base_distinct_nonnull, sum(words IS NULL) base_nulls FROM word_list WHERE rowid>3701;
SELECT count(*) dup_nonnull_within_base FROM (SELECT words FROM word_list WHERE rowid>3701 AND words IS NOT NULL GROUP BY words HAVING count(*)>1);
.print ## row 3702 (first base row) and its neighbours
SELECT rowid, words FROM word_list WHERE rowid BETWEEN 3700 AND 3704;
