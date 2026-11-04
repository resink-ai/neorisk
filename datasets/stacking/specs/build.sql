-- stacking: events → source tables (refdata rebuild, DuckDB).
-- Every child row takes name and version from its run's solutions entity. Floats are the
-- payload's f64, unchanged. The 3 source views are replayed from their stored SQL by verify.

-- table: problem
SELECT ext_id AS name, path, type, target FROM problems;

-- table: solution
SELECT p.ext_id AS name, s.version, s.correlation, s.nb_model, s.nb_feature, s.score,
       s.test_size, s.resampling
FROM solutions s JOIN problems p ON p.problem_key = s.problem;

-- table: eda
SELECT p.ext_id AS name, s.version, e.feature, e.type, e."range" AS "range", e.drop_user,
       e.drop_correlation, e.target
FROM feature_profiled e JOIN solutions s ON s.run_key = e.run
JOIN problems p ON p.problem_key = s.problem;

-- table: model
SELECT p.ext_id AS name, s.version, m.step, m.L1_model
FROM step_completed m JOIN solutions s ON s.run_key = m.run
JOIN problems p ON p.problem_key = s.problem;

-- table: model_score
SELECT p.ext_id AS name, s.version, m.step, m.model, m.train_score, m.test_score
FROM model_scored m JOIN solutions s ON s.run_key = m.run
JOIN problems p ON p.problem_key = s.problem;

-- table: model_importance
SELECT p.ext_id AS name, s.version, m.step, m.model, m.importance
FROM model_weighted m JOIN solutions s ON s.run_key = m.run
JOIN problems p ON p.problem_key = s.problem;

-- table: feature_importance
SELECT p.ext_id AS name, s.version, f.step, f.feature, f.importance
FROM feature_weighted f JOIN solutions s ON s.run_key = f.run
JOIN problems p ON p.problem_key = s.problem;
