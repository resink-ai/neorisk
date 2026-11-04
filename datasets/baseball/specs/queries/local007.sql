-- local007: the average career span in years: per player |Δyears| + |Δmonths|/12 +
-- |Δdays|/365 between debut and final_game (field by field), each part rounded to 2 decimals,
-- then averaged.
-- Written from the question (Spider2 has no gold SQL). It reproduces NEITHER gold variant:
-- local007_a.csv says 4.85 and local007_b.csv 5.09966563; no reading of the question over this
-- file gives either (baseball.md §0.1, scripts g2_local007_search.py). This literal reading
-- over the 18,653 players with a debut gives 4.92375275; the expected answer is ours.
SELECT avg(round(abs(CAST(substr(final_game, 1, 4) AS INTEGER)
                     - CAST(substr(debut, 1, 4) AS INTEGER)), 2)
           + round(abs(CAST(substr(final_game, 6, 2) AS INTEGER)
                       - CAST(substr(debut, 6, 2) AS INTEGER)) / 12.0, 2)
           + round(abs(CAST(substr(final_game, 9, 2) AS INTEGER)
                       - CAST(substr(debut, 9, 2) AS INTEGER)) / 365.0, 2)) AS avg_career_span
FROM player
WHERE debut <> '' AND final_game <> '';
