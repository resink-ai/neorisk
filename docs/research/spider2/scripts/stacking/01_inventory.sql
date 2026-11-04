-- Run: sqlite3 -readonly data/spider2/stacking.sqlite < docs/research/spider2/scripts/stacking/01_inventory.sql
.headers on
.mode list
.print ## objects
SELECT type, name FROM sqlite_master ORDER BY type, name;
.print ## counts
SELECT 'problem' t, count(*) FROM problem UNION ALL SELECT 'solution', count(*) FROM solution UNION ALL SELECT 'model', count(*) FROM model UNION ALL
SELECT 'model_score', count(*) FROM model_score UNION ALL SELECT 'model_importance', count(*) FROM model_importance UNION ALL
SELECT 'feature_importance', count(*) FROM feature_importance UNION ALL SELECT 'eda', count(*) FROM eda UNION ALL
SELECT 'stack_ok (view)', count(*) FROM stack_ok UNION ALL SELECT 'solution_ext (view)', count(*) FROM solution_ext UNION ALL SELECT 'stack_ok_score (view)', count(*) FROM stack_ok_score;
.print ## keys: duplicates on the natural keys
SELECT 'solution(name,version)' k, count(*) - count(DISTINCT name||'|'||version) dups FROM solution UNION ALL
SELECT 'model(name,version,step)', count(*) - count(DISTINCT name||'|'||version||'|'||step) FROM model UNION ALL
SELECT 'model_score(name,version,step,model)', count(*) - count(DISTINCT name||'|'||version||'|'||step||'|'||model) FROM model_score UNION ALL
SELECT 'model_importance(name,version,step,model)', count(*) - count(DISTINCT name||'|'||version||'|'||step||'|'||model) FROM model_importance UNION ALL
SELECT 'feature_importance(name,version,step,feature)', count(*) - count(DISTINCT name||'|'||version||'|'||step||'|'||feature) FROM feature_importance UNION ALL
SELECT 'eda(name,version,feature)', count(*) - count(DISTINCT name||'|'||version||'|'||feature) FROM eda;
.print ## full-row duplicates per table
SELECT 'solution', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM solution)) FROM solution UNION ALL
SELECT 'model', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM model)) FROM model UNION ALL
SELECT 'model_score', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM model_score)) FROM model_score UNION ALL
SELECT 'model_importance', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM model_importance)) FROM model_importance UNION ALL
SELECT 'feature_importance', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM feature_importance)) FROM feature_importance UNION ALL
SELECT 'eda', count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM eda)) FROM eda;
.print ## model_score duplicate keys: are they identical rows or different scores?
SELECT name, version, step, model, count(*) n, count(DISTINCT train_score||'|'||test_score) dv, group_concat(rowid, ' ') rowids FROM model_score GROUP BY 1,2,3,4 HAVING n>1 LIMIT 20;
SELECT count(*) dup_keys, sum(dv>1) differing FROM (SELECT count(*) n, count(DISTINCT train_score||'|'||test_score) dv FROM model_score GROUP BY name, version, step, model HAVING n>1);
.print ## model_importance duplicate keys
SELECT count(*) dup_keys, sum(dv>1) differing FROM (SELECT count(*) n, count(DISTINCT importance) dv FROM model_importance GROUP BY name, version, step, model HAVING n>1);
.print ## feature_importance duplicate keys
SELECT count(*) dup_keys, sum(dv>1) differing FROM (SELECT count(*) n, count(DISTINCT importance) dv FROM feature_importance GROUP BY name, version, step, feature HAVING n>1);
.print ## eda duplicate keys
SELECT count(*) dup_keys, sum(dv>1) differing FROM (SELECT count(*) n, count(DISTINCT type||ifnull("range",'N')||drop_user||drop_correlation||target) dv FROM eda GROUP BY name, version, feature HAVING n>1);
.print ## orphans: every child (name, version) in solution; every name in problem
SELECT 'solution->problem', count(*) FROM solution WHERE name NOT IN (SELECT name FROM problem) UNION ALL
SELECT 'model->solution', count(*) FROM model m WHERE NOT EXISTS (SELECT 1 FROM solution s WHERE s.name=m.name AND s.version=m.version) UNION ALL
SELECT 'model_score->solution', count(*) FROM model_score m WHERE NOT EXISTS (SELECT 1 FROM solution s WHERE s.name=m.name AND s.version=m.version) UNION ALL
SELECT 'model_score->model(step)', count(*) FROM model_score m WHERE NOT EXISTS (SELECT 1 FROM model s WHERE s.name=m.name AND s.version=m.version AND s.step=m.step) UNION ALL
SELECT 'model_importance->model(step)', count(*) FROM model_importance m WHERE NOT EXISTS (SELECT 1 FROM model s WHERE s.name=m.name AND s.version=m.version AND s.step=m.step) UNION ALL
SELECT 'feature_importance->model(step)', count(*) FROM feature_importance m WHERE NOT EXISTS (SELECT 1 FROM model s WHERE s.name=m.name AND s.version=m.version AND s.step=m.step) UNION ALL
SELECT 'eda->solution', count(*) FROM eda m WHERE NOT EXISTS (SELECT 1 FROM solution s WHERE s.name=m.name AND s.version=m.version) UNION ALL
SELECT 'solution without model rows', count(*) FROM solution s WHERE NOT EXISTS (SELECT 1 FROM model m WHERE s.name=m.name AND s.version=m.version) UNION ALL
SELECT 'solution without model_score', count(*) FROM solution s WHERE NOT EXISTS (SELECT 1 FROM model_score m WHERE s.name=m.name AND s.version=m.version) UNION ALL
SELECT 'solution without eda', count(*) FROM solution s WHERE NOT EXISTS (SELECT 1 FROM eda m WHERE s.name=m.name AND s.version=m.version) UNION ALL
SELECT 'problem without solution', count(*) FROM problem p WHERE NOT EXISTS (SELECT 1 FROM solution s WHERE s.name=p.name);
.print ## versions per problem; steps per (name, version) in model
SELECT name, count(*) versions, min(version), max(version) FROM solution GROUP BY 1 ORDER BY rowid;
SELECT steps, count(*) FROM (SELECT name, version, count(*) steps FROM model GROUP BY 1,2) GROUP BY 1;
SELECT 'L1_model constant within (name,version)?', count(*) FROM (SELECT name, version FROM model GROUP BY 1,2 HAVING count(DISTINCT L1_model)>1);
SELECT L1_model, count(*) FROM model GROUP BY 1;
.print ## physical order: rowid order vs (name order of problem, version, step)
SELECT 'solution descents in (problem rowid, version)', sum(pb.rowid < pa.rowid OR (pb.rowid=pa.rowid AND b.version<a.version)) FROM solution a JOIN solution b ON b.rowid=a.rowid+1 JOIN problem pa ON pa.name=a.name JOIN problem pb ON pb.name=b.name;
SELECT 'model descents', sum(pb.rowid < pa.rowid OR (pb.rowid=pa.rowid AND (b.version<a.version OR (b.version=a.version AND b.step<a.step)))) FROM model a JOIN model b ON b.rowid=a.rowid+1 JOIN problem pa ON pa.name=a.name JOIN problem pb ON pb.name=b.name;
SELECT 'model_score descents', sum(pb.rowid < pa.rowid OR (pb.rowid=pa.rowid AND (b.version<a.version OR (b.version=a.version AND b.step<a.step)))) FROM model_score a JOIN model_score b ON b.rowid=a.rowid+1 JOIN problem pa ON pa.name=a.name JOIN problem pb ON pb.name=b.name;
SELECT 'model_importance descents', sum(pb.rowid < pa.rowid OR (pb.rowid=pa.rowid AND (b.version<a.version OR (b.version=a.version AND b.step<a.step)))) FROM model_importance a JOIN model_importance b ON b.rowid=a.rowid+1 JOIN problem pa ON pa.name=a.name JOIN problem pb ON pb.name=b.name;
SELECT 'feature_importance descents', sum(pb.rowid < pa.rowid OR (pb.rowid=pa.rowid AND (b.version<a.version OR (b.version=a.version AND b.step<a.step)))) FROM feature_importance a JOIN feature_importance b ON b.rowid=a.rowid+1 JOIN problem pa ON pa.name=a.name JOIN problem pb ON pb.name=b.name;
SELECT 'eda descents', sum(pb.rowid < pa.rowid OR (pb.rowid=pa.rowid AND b.version<a.version)) FROM eda a JOIN eda b ON b.rowid=a.rowid+1 JOIN problem pa ON pa.name=a.name JOIN problem pb ON pb.name=b.name;
