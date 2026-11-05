-- Run: sqlite3 -readonly data/spider2/stacking.sqlite < docs/research/spider2/scripts/stacking/03_derived.sql
-- Which columns are functions of other rows (candidates for derivation rules), and lifecycle relations.
.headers on
.mode list
.print ## eda: type/range NULL exactly on drop_user=1 or target=1 rows?
SELECT drop_user, target, type IS NULL t_null, "range" IS NULL r_null, count(*) FROM eda GROUP BY 1,2,3,4;
.print ## step 3 feature count vs solution.nb_feature
SELECT sum(n=s.nb_feature) eq, sum(n<s.nb_feature) lt, sum(n>s.nb_feature) gt FROM (SELECT name, version, count(*) n FROM feature_importance WHERE step=3 GROUP BY 1,2) f JOIN solution s USING (name, version);
.print ## step 1 vs step 2 feature sets and values
SELECT count(*) step1_rows_without_equal_step2 FROM feature_importance a WHERE step=1 AND NOT EXISTS (SELECT 1 FROM feature_importance b WHERE b.name=a.name AND b.version=a.version AND b.step=2 AND b.feature=a.feature AND b.importance=a.importance);
SELECT count(*) step1_features_missing_in_step2 FROM feature_importance a WHERE step=1 AND NOT EXISTS (SELECT 1 FROM feature_importance b WHERE b.name=a.name AND b.version=a.version AND b.step=2 AND b.feature=a.feature);
.print ## step 3 features = top-nb_feature of step 2 by importance?
WITH r AS (SELECT name, version, feature, importance, rank() OVER (PARTITION BY name, version ORDER BY importance DESC) rk FROM feature_importance WHERE step=2)
SELECT count(*) step3_not_in_top_nb_feature FROM feature_importance f JOIN solution s USING (name, version)
 WHERE f.step=3 AND NOT EXISTS (SELECT 1 FROM r WHERE r.name=f.name AND r.version=f.version AND r.feature=f.feature AND r.rk<=s.nb_feature);
.print ## step 1 features = eda rows with drop_user=0 and target=0 (correlation-dropped included)
SELECT count(*) eda_kept_not_in_step1 FROM eda e WHERE drop_user=0 AND target=0 AND NOT EXISTS (SELECT 1 FROM feature_importance f WHERE f.name=e.name AND f.version=e.version AND f.step=1 AND f.feature=e.feature);
SELECT count(*) step1_not_eda_kept FROM feature_importance f WHERE step=1 AND NOT EXISTS (SELECT 1 FROM eda e WHERE f.name=e.name AND f.version=e.version AND e.feature=f.feature AND drop_user=0 AND target=0);
.print ## step 2 features = step1 minus drop_correlation? (count rows of step2 whose eda drop_correlation=1)
SELECT count(*) FROM feature_importance f JOIN eda e ON e.name=f.name AND e.version=f.version AND e.feature=f.feature WHERE f.step=2 AND e.drop_correlation=1;
.print ## model rows per step (excluding Stack) and vs solution.nb_model
SELECT step, round(avg(n),2) avg_models, min(n), max(n) FROM (SELECT name, version, step, count(*) n FROM model_score WHERE model<>'Stack' GROUP BY 1,2,3) GROUP BY 1;
SELECT step, sum(n=s.nb_model) eq_nb_model, sum(n<>s.nb_model) ne FROM (SELECT name, version, step, count(*) n FROM model_score WHERE model<>'Stack' GROUP BY 1,2,3) m JOIN solution s USING (name, version) GROUP BY 1;
.print ## step 2/3 model sets are subsets of step 1?
SELECT count(*) step2_models_not_in_step1 FROM model_score a WHERE step=2 AND model<>'Stack' AND NOT EXISTS (SELECT 1 FROM model_score b WHERE b.name=a.name AND b.version=a.version AND b.step=1 AND b.model=a.model);
SELECT count(*) step3_models_not_in_step2 FROM model_score a WHERE step=3 AND model<>'Stack' AND NOT EXISTS (SELECT 1 FROM model_score b WHERE b.name=a.name AND b.version=a.version AND b.step=2 AND b.model=a.model);
.print ## step 2 models = step 1 models with test_score >= solution.score ?
SELECT sum(in2 = (a.test_score >= s.score)) agree, sum(in2 <> (a.test_score >= s.score)) disagree FROM (
  SELECT a.*, EXISTS (SELECT 1 FROM model_score b WHERE b.name=a.name AND b.version=a.version AND b.step=2 AND b.model=a.model) in2 FROM model_score a WHERE step=1 AND model<>'Stack') a
JOIN solution s USING (name, version);
.print ## step 2 models = top nb_model of step 1 by test_score?
WITH r AS (SELECT name, version, model, rank() OVER (PARTITION BY name, version ORDER BY test_score DESC) rk FROM model_score WHERE step=1 AND model<>'Stack')
SELECT sum(in2 = (rk <= s.nb_model)) agree, sum(in2 <> (rk <= s.nb_model)) disagree FROM (
  SELECT r.*, EXISTS (SELECT 1 FROM model_score b WHERE b.name=r.name AND b.version=r.version AND b.step=2 AND b.model=r.model) in2 FROM r) x JOIN solution s USING (name, version);
.print ## step 2 and 3 model scores equal step 1 scores for the same model?
SELECT a.step, sum(a.train_score=b.train_score AND a.test_score=b.test_score) same, sum(NOT (a.train_score=b.train_score AND a.test_score=b.test_score)) diff FROM model_score a JOIN model_score b ON b.name=a.name AND b.version=a.version AND b.model=a.model AND b.step=1 WHERE a.step>1 AND a.model<>'Stack' GROUP BY 1;
.print ## model_importance: models = non-Stack models of the step? (1 extra, 3 missing measured in 02)
SELECT i.name, i.version, i.step, i.model FROM model_importance i WHERE NOT EXISTS (SELECT 1 FROM model_score s WHERE i.name=s.name AND i.version=s.version AND i.step=s.step AND i.model=s.model);
SELECT s.name, s.version, s.step, s.model FROM model_score s WHERE s.model<>'Stack' AND NOT EXISTS (SELECT 1 FROM model_importance i WHERE i.name=s.name AND i.version=s.version AND i.step=s.step AND i.model=s.model);
.print ## Stack vs best base model per step: strong (<), soft (=), weak (>)
SELECT step, sum(mx<st) strong, sum(mx=st) soft, sum(mx>st) weak FROM (
  SELECT a.name, a.version, a.step, max(a.test_score) mx, (SELECT test_score FROM model_score b WHERE b.name=a.name AND b.version=a.version AND b.step=a.step AND b.model='Stack') st
  FROM model_score a WHERE a.model<>'Stack' GROUP BY 1,2,3) GROUP BY 1;
.print ## problem.type vs model names (C models on classification, R models on regression)
SELECT p.type, sum(m.model LIKE '%C%' AND m.model NOT IN ('Stack')) c_like, count(*) n FROM model_score m JOIN problem p ON p.name=m.name GROUP BY 1;
.print ## L1_model per (name, version) vs solution columns: does it vary with version?
SELECT name, group_concat(version||':'||L1_model, ' ') FROM (SELECT DISTINCT name, version, L1_model FROM model ORDER BY name, version) GROUP BY 1;
.print ## the views are pure functions of model and model_score (SQL in sqlite_master); solution_ext = DISTINCT (name,version,L1_model) of model
SELECT count(*) FROM (SELECT name, version, L1_model FROM solution_ext EXCEPT SELECT DISTINCT name, version, L1_model FROM model);
.print ## score precision: digits after the point (as text)
SELECT length(CAST(test_score AS TEXT)) - instr(CAST(test_score AS TEXT), '.') dec, count(*) FROM model_score WHERE typeof(test_score)='real' GROUP BY 1 ORDER BY 1;
SELECT length(CAST(importance AS TEXT)) - instr(CAST(importance AS TEXT), '.') dec, count(*) FROM model_importance WHERE typeof(importance)='real' GROUP BY 1 ORDER BY 1;
.print ## negative test scores (regression R2 below 0)
SELECT count(*) neg_test, min(test_score) FROM model_score WHERE test_score<0;
SELECT count(*) neg_train, min(train_score) FROM model_score WHERE train_score<0;
.print ## step 2 models = top nb_model of step 1 by step-1 model_importance?
WITH r AS (SELECT name, version, model, rank() OVER (PARTITION BY name, version ORDER BY importance DESC) rk FROM model_importance WHERE step=1)
SELECT sum(in2 = (rk <= s.nb_model)) agree, sum(in2 <> (rk <= s.nb_model)) disagree FROM (
  SELECT r.*, EXISTS (SELECT 1 FROM model_score b WHERE b.name=r.name AND b.version=r.version AND b.step=2 AND b.model=r.model) in2 FROM r) x JOIN solution s USING (name, version);
.print ## step 3 model set = step 2 model set?
SELECT count(*) FROM (SELECT name, version, model FROM model_score WHERE step=2 EXCEPT SELECT name, version, model FROM model_score WHERE step=3);
SELECT count(*) FROM (SELECT name, version, model FROM model_score WHERE step=3 EXCEPT SELECT name, version, model FROM model_score WHERE step=2);
.print ## the two (name,version) whose step-2 model count differs from nb_model
SELECT m.name, m.version, m.step, count(*) n, s.nb_model FROM model_score m JOIN solution s USING (name, version) WHERE m.model<>'Stack' AND m.step>1 GROUP BY 1,2,3 HAVING n<>s.nb_model;
