-- local264: the L1_model that appears most often across all steps and versions, and its
-- count, over the 303 model rows.
-- Written from the question (no gold SQL). Reproduces gold variant local264_a.csv:
-- regression 213 (_b says the same with a 'Traditional' label; _c is the 303-row total).
SELECT L1_model AS model_category, count(*) AS total_count
FROM model
GROUP BY L1_model
ORDER BY total_count DESC
LIMIT 1;
