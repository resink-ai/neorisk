-- Run: sqlite3 -readonly data/spider2/stacking.sqlite < docs/research/spider2/scripts/stacking/02_values.sql
.headers on
.mode list
.print ## solution in rowid order (the insertion order)
SELECT group_concat(name||'#'||version, ' ; ') FROM (SELECT name, version FROM solution ORDER BY rowid);
.print ## where (name, version) blocks of each child table start, in rowid order: does every table follow solution's order?
WITH s AS (SELECT name, version, row_number() OVER (ORDER BY rowid) k FROM solution),
f AS (SELECT 'model' t, name, version, min(rowid) r FROM model GROUP BY 2,3 UNION ALL
      SELECT 'model_score', name, version, min(rowid) FROM model_score GROUP BY 2,3 UNION ALL
      SELECT 'model_importance', name, version, min(rowid) FROM model_importance GROUP BY 2,3 UNION ALL
      SELECT 'feature_importance', name, version, min(rowid) FROM feature_importance GROUP BY 2,3 UNION ALL
      SELECT 'eda', name, version, min(rowid) FROM eda GROUP BY 2,3),
o AS (SELECT t, k, row_number() OVER (PARTITION BY t ORDER BY r) rk FROM f JOIN s USING (name, version))
SELECT t, sum(k<>rk) blocks_out_of_solution_order, count(*) blocks FROM o GROUP BY t;
.print ## are child blocks contiguous (no interleaving of (name,version))?
SELECT 'model_score', count(*) FROM (SELECT name, version, max(rowid)-min(rowid)+1 span, count(*) n FROM model_score GROUP BY 1,2) WHERE span<>n UNION ALL
SELECT 'model_importance', count(*) FROM (SELECT name, version, max(rowid)-min(rowid)+1 span, count(*) n FROM model_importance GROUP BY 1,2) WHERE span<>n UNION ALL
SELECT 'feature_importance', count(*) FROM (SELECT name, version, max(rowid)-min(rowid)+1 span, count(*) n FROM feature_importance GROUP BY 1,2) WHERE span<>n UNION ALL
SELECT 'eda', count(*) FROM (SELECT name, version, max(rowid)-min(rowid)+1 span, count(*) n FROM eda GROUP BY 1,2) WHERE span<>n;
.print ## storage types of NUMERIC / BLOB columns
SELECT 'solution.correlation', typeof(correlation), count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'solution.score', typeof(score), count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'solution.test_size', typeof(test_size), count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'model_score.train_score', typeof(train_score), count(*) FROM model_score GROUP BY 2 UNION ALL
SELECT 'model_score.test_score', typeof(test_score), count(*) FROM model_score GROUP BY 2 UNION ALL
SELECT 'model_importance.importance', typeof(importance), count(*) FROM model_importance GROUP BY 2 UNION ALL
SELECT 'feature_importance.importance', typeof(importance), count(*) FROM feature_importance GROUP BY 2 UNION ALL
SELECT 'eda.range', typeof("range"), count(*) FROM eda GROUP BY 2 UNION ALL
SELECT 'eda.type', typeof(type), count(*) FROM eda GROUP BY 2;
.print ## integer-valued NUMERIC cells (stored as integer): which values
SELECT 'model_score.test_score', test_score, count(*) FROM model_score WHERE typeof(test_score)='integer' GROUP BY 2 UNION ALL
SELECT 'model_score.train_score', train_score, count(*) FROM model_score WHERE typeof(train_score)='integer' GROUP BY 2 UNION ALL
SELECT 'feature_importance', importance, count(*) FROM feature_importance WHERE typeof(importance)='integer' GROUP BY 2 UNION ALL
SELECT 'model_importance', importance, count(*) FROM model_importance WHERE typeof(importance)='integer' GROUP BY 2;
.print ## solution value sets
SELECT 'correlation', correlation, count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'nb_model', nb_model, count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'nb_feature', nb_feature, count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'score', score, count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'test_size', test_size, count(*) FROM solution GROUP BY 2 UNION ALL
SELECT 'resampling', resampling, count(*) FROM solution GROUP BY 2;
.print ## models in model_score, and per (name,version,step) counts
SELECT model, count(*) n, count(DISTINCT name) problems FROM model_score GROUP BY 1 ORDER BY 2 DESC;
SELECT n, count(*) FROM (SELECT count(*) n FROM model_score GROUP BY name, version, step) GROUP BY 1 ORDER BY 1;
SELECT 'every (name,version,step) has a Stack row', count(*) FROM model m WHERE NOT EXISTS (SELECT 1 FROM model_score s WHERE s.name=m.name AND s.version=m.version AND s.step=m.step AND s.model='Stack');
.print ## model_importance models vs model_score models (per step): models scored but without importance and vice versa
SELECT 'score_not_importance', count(*) FROM model_score s WHERE NOT EXISTS (SELECT 1 FROM model_importance i WHERE i.name=s.name AND i.version=s.version AND i.step=s.step AND i.model=s.model) UNION ALL
SELECT 'importance_not_score', count(*) FROM model_importance i WHERE NOT EXISTS (SELECT 1 FROM model_score s WHERE i.name=s.name AND i.version=s.version AND i.step=s.step AND i.model=s.model);
SELECT model, count(*) FROM model_score s WHERE NOT EXISTS (SELECT 1 FROM model_importance i WHERE i.name=s.name AND i.version=s.version AND i.step=s.step AND i.model=s.model) GROUP BY 1;
.print ## model_importance sums to 1 per (name,version,step)?
SELECT sum(abs(t-1)<1e-9) sum_1, sum(abs(t-1)>=1e-9) not_1, min(t), max(t) FROM (SELECT sum(importance) t FROM model_importance GROUP BY name, version, step);
.print ## feature_importance sums to 1 per (name,version,step)?
SELECT sum(abs(t-1)<1e-9) sum_1, sum(abs(t-1)>=1e-9) not_1, min(t), max(t) FROM (SELECT sum(importance) t FROM feature_importance GROUP BY name, version, step);
.print ## steps: does feature count shrink with step?
SELECT step, count(*) rows, round(avg(n),2) avg_features FROM (SELECT name, version, step, count(*) n FROM feature_importance GROUP BY 1,2,3) GROUP BY 1;
.print ## feature_importance features vs eda features (non-dropped, non-target)
SELECT 'fi features not in eda', count(*) FROM feature_importance f WHERE NOT EXISTS (SELECT 1 FROM eda e WHERE e.name=f.name AND e.version=f.version AND e.feature=f.feature);
SELECT 'step1 fi features = eda features kept (drop_user=0, drop_correlation=0, target=0)?', count(*) FROM (
  SELECT name, version, feature FROM eda WHERE drop_user=0 AND drop_correlation=0 AND target=0
  EXCEPT SELECT name, version, feature FROM feature_importance WHERE step=1);
SELECT 'step1 fi not in kept eda', count(*) FROM (
  SELECT name, version, feature FROM feature_importance WHERE step=1
  EXCEPT SELECT name, version, feature FROM eda WHERE drop_user=0 AND drop_correlation=0 AND target=0);
.print ## eda value sets
SELECT type, count(*) FROM eda GROUP BY 1;
SELECT drop_user, drop_correlation, target, count(*) FROM eda GROUP BY 1,2,3;
SELECT 'one target per (name,version)', count(*) FROM (SELECT name, version FROM eda GROUP BY 1,2 HAVING sum(target)<>1);
SELECT 'eda target feature = problem.target', count(*) mismatches FROM eda e JOIN problem p ON p.name=e.name WHERE e.target=1 AND e.feature<>p.target;
SELECT e.name, e.feature, p.target FROM eda e JOIN problem p ON p.name=e.name WHERE e.target=1 AND e.feature<>p.target GROUP BY 1,2,3;
.print ## eda range text samples by type
SELECT type, "range" FROM eda WHERE rowid IN (SELECT min(rowid) FROM eda GROUP BY type, substr("range",1,1));
.print ## text oddities in problem
SELECT name, length(target), target<>trim(target) untrimmed FROM problem WHERE target<>trim(target) OR name<>trim(name);
