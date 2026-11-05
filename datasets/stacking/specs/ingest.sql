-- stacking: source tables → events (refdata ingest).
-- The source has no times. The run clock (a rule): run k, the k-th solution rowid, starts at
-- 2023-01-01 00:00:00 + k hours. Its eda rows are at the start; its step-s rows are at
-- + s minutes, then + 0/1/2/3 seconds for scores, model weights, feature weights and the
-- step's completion, so equal times never mix the lifecycle. ord is the source rowid.
-- Scores and importances are NUMERIC: they travel as f64, bit-exact.

-- entity: problems
SELECT p.name AS ext_id,
       (SELECT datetime('2023-01-01 00:00:00', '+' || min(s.rowid) || ' hours')
        FROM solution s WHERE s.name = p.name) AS created_at,
       p.path AS path, p.type AS type, p.target AS target
FROM problem p ORDER BY p.rowid;

-- entity: solutions
SELECT name || '#' || version AS ext_id,
       datetime('2023-01-01 00:00:00', '+' || rowid || ' hours') AS created_at,
       name AS problem, version, correlation, nb_model, nb_feature, score, test_size, resampling
FROM solution ORDER BY rowid;

-- event: feature_profiled owner=run ord=src_rowid
SELECT datetime('2023-01-01 00:00:00', '+' || s.rowid || ' hours') AS event_time,
       e.name || '#' || e.version AS run, e.rowid AS src_rowid, e.feature, e.type,
       e."range" AS "range", e.drop_user, e.drop_correlation, e.target
FROM eda e JOIN solution s ON s.name = e.name AND s.version = e.version ORDER BY e.rowid;

-- event: model_scored owner=run ord=src_rowid
SELECT datetime('2023-01-01 00:00:00', '+' || s.rowid || ' hours',
                '+' || m.step || ' minutes') AS event_time,
       m.name || '#' || m.version AS run, m.rowid AS src_rowid, m.step, m.model,
       m.train_score, m.test_score
FROM model_score m JOIN solution s ON s.name = m.name AND s.version = m.version
ORDER BY m.rowid;

-- event: model_weighted owner=run ord=src_rowid
SELECT datetime('2023-01-01 00:00:00', '+' || s.rowid || ' hours',
                '+' || m.step || ' minutes', '+1 seconds') AS event_time,
       m.name || '#' || m.version AS run, m.rowid AS src_rowid, m.step, m.model, m.importance
FROM model_importance m JOIN solution s ON s.name = m.name AND s.version = m.version
ORDER BY m.rowid;

-- event: feature_weighted owner=run ord=src_rowid
SELECT datetime('2023-01-01 00:00:00', '+' || s.rowid || ' hours',
                '+' || f.step || ' minutes', '+2 seconds') AS event_time,
       f.name || '#' || f.version AS run, f.rowid AS src_rowid, f.step, f.feature, f.importance
FROM feature_importance f JOIN solution s ON s.name = f.name AND s.version = f.version
ORDER BY f.rowid;

-- event: step_completed owner=run ord=src_rowid
SELECT datetime('2023-01-01 00:00:00', '+' || s.rowid || ' hours',
                '+' || m.step || ' minutes', '+3 seconds') AS event_time,
       m.name || '#' || m.version AS run, m.rowid AS src_rowid, m.step, m.L1_model
FROM model m JOIN solution s ON s.name = m.name AND s.version = m.version ORDER BY m.rowid;
