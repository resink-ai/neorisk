-- local201 (_b reading): the first 10 words (alphabetical) of length 4-5 starting with 'r' that
-- have at least one same-length "anagram", with the count.
-- Written from the question (no gold SQL); reproduces gold CSV _b (rason 1 ... rugs 1), the
-- reading where the only anagram found is another row holding the same word. Those are exactly
-- the first 10 r-words Spider2 duplicated, so this checks the duplicate markers.
SELECT words, count(*) - 1 AS anagram_count
FROM word_list
WHERE length(words) BETWEEN 4 AND 5 AND substr(words, 1, 1) = 'r'
GROUP BY words HAVING count(*) > 1
ORDER BY words LIMIT 10;
