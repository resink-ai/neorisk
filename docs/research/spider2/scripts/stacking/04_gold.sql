-- Run: sqlite3 -readonly data/spider2/stacking.sqlite < docs/research/spider2/scripts/stacking/04_gold.sql
-- Readings of local262/263/264 against the gold CSVs (no gold SQL exists).
.headers on
.mode list
.print ## stack_ok view: rows by status and L1_model
SELECT status, L1_model, count(*) n FROM stack_ok GROUP BY 1,2 ORDER BY 1,2;
.print ## local263 R1: per status, the L1_model with most stack_ok rows   (gold _a: soft regression 17; strong regression 37)
WITH c AS (SELECT status, L1_model, count(*) n FROM stack_ok GROUP BY 1,2),
r AS (SELECT *, rank() OVER (PARTITION BY status ORDER BY n DESC) rk FROM c)
SELECT status, L1_model, n FROM r WHERE rk=1 ORDER BY status;
.print ## local263 R2: as R1 but counting distinct (name, version) per status
WITH c AS (SELECT status, L1_model, count(DISTINCT name||'#'||version) n FROM stack_ok GROUP BY 1,2),
r AS (SELECT *, rank() OVER (PARTITION BY status ORDER BY n DESC) rk FROM c)
SELECT status, L1_model, n FROM r WHERE rk=1 ORDER BY status;
.print ## local264 R1: L1_model frequency over model rows (all steps, versions)   (gold _a regression 213; _b Traditional regression 213; _c Traditional 303)
SELECT L1_model, count(*) n FROM model GROUP BY 1 ORDER BY 2 DESC;
SELECT 'all model rows', count(*) FROM model;
.print ## local262 R1: problems whose count of strong (name,version,step) rows exceeds their solution row count
.print ## (gold _a: Critical Heat Flux, Delaney solubility, Franck-Hertz, PSS3E5, Solar Power Generation, Tunnel diode, oil spill)
WITH s AS (SELECT a.name, a.version, a.step, max(a.test_score) mx, (SELECT test_score FROM model_score b WHERE b.name=a.name AND b.version=a.version AND b.step=a.step AND b.model='Stack') st
           FROM model_score a WHERE a.model<>'Stack' GROUP BY 1,2,3),
strong AS (SELECT name, count(*) n FROM s WHERE mx<st GROUP BY 1),
sol AS (SELECT name, count(*) n FROM solution GROUP BY 1)
SELECT strong.name, strong.n strong_steps, sol.n solutions FROM strong JOIN sol USING (name) WHERE strong.n > sol.n ORDER BY 1;
.print ## local262 R2: same via the stack_ok view (strong rows)
SELECT k.name, k.n, s.n FROM (SELECT name, count(*) n FROM stack_ok WHERE status='strong' GROUP BY 1) k JOIN (SELECT name, count(*) n FROM solution GROUP BY 1) s USING (name) WHERE k.n>s.n ORDER BY 1;
.print ## stack_ok has one row per (name,version,step)? and covers strong+soft exactly
SELECT count(*) rows, count(DISTINCT name||'#'||version||'#'||step) keys FROM stack_ok;
.print ## stack_ok_score: (name, version) with a Stack score at all 3 steps among stack_ok (name,version)
SELECT count(*), count(DISTINCT name||'#'||version) FROM stack_ok_score;
.print ## local263 R3: one status per (name, version): strong if any step strong, else soft if any step soft; count per L1_model
WITH nv AS (SELECT name, version, L1_model, max(status='strong') any_strong FROM stack_ok GROUP BY 1,2,3),
c AS (SELECT CASE WHEN any_strong THEN 'strong' ELSE 'soft' END status, L1_model, count(*) n FROM nv GROUP BY 1,2)
SELECT * FROM c ORDER BY 1,2;
