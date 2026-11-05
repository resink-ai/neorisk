-- local201: the first 10 words (alphabetical) of length 4-5 starting with 'r' that have at
-- least one same-length anagram (case-sensitive), with the number of such anagrams.
-- Written from the question (no gold SQL); reproduces gold CSV _a (raad 3 ... race 5): an
-- anagram is another distinct word with the same sorted letters. Byte comparison throughout,
-- so case counts (no LIKE).
WITH RECURSIVE w AS (SELECT DISTINCT words FROM word_list
                     WHERE length(words) BETWEEN 4 AND 5),
     ch(words, i, c) AS (SELECT words, 1, substr(words, 1, 1) FROM w
                         UNION ALL
                         SELECT words, i + 1, substr(words, i + 1, 1) FROM ch
                         WHERE i < length(words)),
     s AS (SELECT words, group_concat(c, '' ORDER BY c) AS sig FROM ch GROUP BY words)
SELECT a.words AS word, count(*) AS anagram_count
FROM s a JOIN s b ON b.sig = a.sig AND b.words <> a.words
WHERE substr(a.words, 1, 1) = 'r'
GROUP BY a.words ORDER BY a.words LIMIT 10;
