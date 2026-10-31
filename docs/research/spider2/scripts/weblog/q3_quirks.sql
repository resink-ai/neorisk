-- Quirks: block variants of activity_log, order within sessions, ties, vocabularies.
-- Blocks (from blocks.py): activity_log A = rowid 1-32 (x2), B = 65-100 (x3), C = 173-208 (x2).
-- name: activity_variant_counts
SELECT CASE WHEN rowid<=64 THEN 'A' WHEN rowid<=172 THEN 'B' ELSE 'C' END v, count(*) n,
  sum(path LIKE '%/' AND path<>'/') trailing_slash, sum(path='') empty_path, sum(path='/') root_path,
  count(DISTINCT session) sessions, group_concat(DISTINCT path) paths
FROM activity_log GROUP BY 1;
-- name: activity_A_vs_B_normalised
-- A rows (one copy) whose (stamp, session, option, rtrim(path,'/'), search_type) appear in B (one copy), and vice versa
WITH a AS (SELECT stamp, session, action, option, CASE WHEN path='/' THEN '' ELSE rtrim(path,'/') END p, search_type FROM activity_log WHERE rowid BETWEEN 1 AND 32),
     b AS (SELECT stamp, session, action, option, path p, search_type FROM activity_log WHERE rowid BETWEEN 65 AND 100)
SELECT (SELECT count(*) FROM a) n_a, (SELECT count(*) FROM b) n_b,
  (SELECT count(*) FROM (SELECT * FROM a INTERSECT SELECT * FROM b)) common,
  (SELECT group_concat(session||' '||stamp||' '||p, '; ') FROM (SELECT * FROM a EXCEPT SELECT * FROM b)) only_a,
  (SELECT group_concat(session||' '||stamp||' '||p||' '||search_type, '; ') FROM (SELECT * FROM b EXCEPT SELECT * FROM a)) only_b;
-- name: activity_B_vs_C
WITH b AS (SELECT stamp, session, action, option, path, search_type FROM activity_log WHERE rowid BETWEEN 65 AND 100),
     c AS (SELECT stamp, session, action, option, CASE WHEN path='/' THEN '' ELSE path END, search_type FROM activity_log WHERE rowid BETWEEN 173 AND 208)
SELECT (SELECT count(*) FROM (SELECT * FROM b EXCEPT SELECT * FROM c)) b_not_c, (SELECT count(*) FROM (SELECT * FROM c EXCEPT SELECT * FROM b)) c_not_b;
-- name: rowid_time_descents
-- consecutive rows (rowid order) of the same session whose stamp goes backwards
WITH x AS (SELECT 'action_log' t, rowid r, session, stamp FROM action_log
  UNION ALL SELECT 'activity_log', rowid, session, stamp FROM activity_log
  UNION ALL SELECT 'form_log', rowid, session, stamp FROM form_log
  UNION ALL SELECT 'form_error_log', rowid, session, stamp FROM form_error_log
  UNION ALL SELECT 'read_log', rowid, session, stamp FROM read_log
  UNION ALL SELECT 'dup_action_log', rowid, session, stamp FROM dup_action_log
  UNION ALL SELECT 'access_log(ok)', rowid, session, stamp FROM access_log WHERE datetime(stamp) IS NOT NULL),
y AS (SELECT t, r, session, stamp, lag(stamp) OVER (PARTITION BY t ORDER BY r) ps, lag(session) OVER (PARTITION BY t ORDER BY r) pss FROM x)
SELECT t, count(*) n, sum(session=pss) same_session_pairs, sum(session=pss AND stamp<ps) descents_within_session,
  sum(session<>pss AND stamp<ps) descents_at_session_change FROM y GROUP BY t ORDER BY t;
-- name: action_log_block_order
-- first block (rowid 1-20) in rowid order: purchase listed before the views it follows
SELECT rowid, session, action, products, stamp FROM action_log WHERE rowid<=20 ORDER BY rowid;
-- name: ties_within_session
-- (session, stamp) groups with more than one row; how many are full duplicates
WITH g AS (SELECT 'activity_log' t, session, stamp, count(*) n, count(DISTINCT path||'|'||option||'|'||search_type) nd FROM activity_log GROUP BY session, stamp
  UNION ALL SELECT 'action_log', session, stamp, count(*), count(DISTINCT action||'|'||coalesce(products,'')||'|'||coalesce(amount,'')) FROM action_log GROUP BY session, stamp
  UNION ALL SELECT 'form_log', session, stamp, count(*), count(DISTINCT path||'|'||status) FROM form_log GROUP BY session, stamp
  UNION ALL SELECT 'form_error_log', session, stamp, count(*), count(DISTINCT field||'|'||error_type) FROM form_error_log GROUP BY session, stamp)
SELECT t, count(*) groups, sum(n>1) tied_groups, sum(CASE WHEN n>1 THEN n END) rows_in_ties, sum(n>1 AND nd>1) ties_with_different_content
FROM g GROUP BY t;
-- name: ties_within_session_one_copy
-- same as above on one copy of each block (action_log 1-20, activity_log B 65-100, form_log 1-15)
WITH g AS (SELECT 'activity_log B' t, session, stamp, count(*) n FROM activity_log WHERE rowid BETWEEN 65 AND 100 GROUP BY session, stamp
  UNION ALL SELECT 'action_log 1-20', session, stamp, count(*) FROM action_log WHERE rowid<=20 GROUP BY session, stamp
  UNION ALL SELECT 'form_log 1-15', session, stamp, count(*) FROM form_log WHERE rowid<=15 GROUP BY session, stamp)
SELECT t, count(*) groups, sum(n>1) tied_groups, sum(CASE WHEN n>1 THEN n END) rows_in_ties FROM g GROUP BY t;
-- name: activity_session_starts
-- in each activity variant, the first stamp of every session and whether all sessions start at one instant
SELECT CASE WHEN rowid<=64 THEN 'A' WHEN rowid<=172 THEN 'B' ELSE 'C' END v, count(DISTINCT session) sessions,
  count(DISTINCT session) FILTER (WHERE stamp='2017-01-09 12:18:43') start_at_121843
FROM activity_log GROUP BY 1;
-- name: activity_gaps
-- seconds between consecutive distinct stamps within a session, variant B one copy
WITH b AS (SELECT DISTINCT session, stamp FROM activity_log WHERE rowid BETWEEN 65 AND 100),
g AS (SELECT session, (julianday(stamp)-julianday(lag(stamp) OVER (PARTITION BY session ORDER BY stamp)))*86400 gap FROM b)
SELECT round(gap) gap_s, count(*) n FROM g WHERE gap IS NOT NULL GROUP BY 1 ORDER BY 1;
-- name: activity_events_per_session_B
SELECT n, count(*) sessions FROM (SELECT session, count(*) n FROM activity_log WHERE rowid BETWEEN 65 AND 100 GROUP BY session) GROUP BY n ORDER BY n;
-- name: activity_vocab
SELECT option, path, search_type, count(*) n FROM activity_log GROUP BY 1,2,3 ORDER BY n DESC, 1, 2, 3;
-- name: action_log_vocab
SELECT action, category, products, amount, count(*) n FROM action_log GROUP BY 1,2,3,4 ORDER BY n DESC;
-- name: purchase_amount_vs_products
-- action_log purchase: amount = 1000 x number of products?
SELECT products, amount, length(products)-length(replace(products, ',', ''))+1 n_products, count(*) n FROM action_log WHERE action='purchase' GROUP BY 1,2;
-- name: form_log_flow
SELECT session, group_concat(substr(stamp,12)||' '||path||CASE WHEN status<>'' THEN '['||status||']' ELSE '' END, ' > ') flow
FROM (SELECT rowid r, * FROM form_log WHERE rowid<=15 ORDER BY rowid) GROUP BY session ORDER BY min(r);
-- name: form_status_counts
SELECT status, count(*) n FROM form_log GROUP BY 1;
-- name: form_error_vocab
SELECT form, field, error_type, value, count(*) n FROM form_error_log GROUP BY 1,2,3,4 ORDER BY 1,2,3;
-- name: read_log_flow
SELECT session, url, group_concat(action||'@'||substr(stamp,15), ' ') steps, count(*) n,
  (julianday(max(stamp))-julianday(min(stamp)))*86400 span_s
FROM (SELECT rowid r, * FROM read_log ORDER BY rowid) GROUP BY session, url ORDER BY min(r);
-- name: read_depth_distribution
SELECT max_depth, count(*) sessions FROM (SELECT session, max(CASE action WHEN 'view' THEN 0 ELSE CAST(replace(replace(action,'read-',''),'%','') AS INT) END) max_depth FROM read_log GROUP BY session) GROUP BY 1 ORDER BY 1;
-- name: mst_users_mix_variant
-- one copy of each user version: V1 = rowid 71-100, V2 = rowid 101-130
SELECT CASE WHEN rowid BETWEEN 71 AND 100 THEN 'V1' ELSE 'V2' END v, sex, register_device, count(*) n
FROM mst_users WHERE rowid BETWEEN 71 AND 130 GROUP BY 1,2,3 ORDER BY 1,2,3;
-- name: mst_users_withdraw
SELECT user_id, register_date, withdraw_date, count(*) n FROM mst_users WHERE withdraw_date IS NOT NULL GROUP BY 1,2,3;
-- name: mst_users_register_by_month_V1
SELECT substr(register_date,1,7) m, count(*) n FROM mst_users WHERE rowid BETWEEN 71 AND 100 GROUP BY 1;
-- name: birth_year_hist
SELECT substr(birth_date,1,3)||'0s' decade, count(*) users FROM mst_users WHERE rowid BETWEEN 71 AND 100 GROUP BY 1 ORDER BY 1;
-- name: activity_B_option_mix
SELECT option, count(*) n FROM activity_log WHERE rowid BETWEEN 65 AND 100 GROUP BY 1;
-- name: action_log_one_copy_mix
SELECT action, count(*) n FROM action_log WHERE rowid<=20 GROUP BY 1;
-- name: activity_gap_median
WITH b AS (SELECT DISTINCT session, stamp FROM activity_log WHERE rowid BETWEEN 65 AND 100),
g AS (SELECT (julianday(stamp)-julianday(lag(stamp) OVER (PARTITION BY session ORDER BY stamp)))*86400 gap FROM b),
o AS (SELECT round(gap) gap, row_number() OVER (ORDER BY gap) k, count(*) OVER () n FROM g WHERE gap IS NOT NULL)
SELECT n, avg(gap) median_s FROM o WHERE k IN ((n+1)/2, (n+2)/2);
