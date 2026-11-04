"""DuckDB check: rebuild SalaryDataset.Salary byte-exact from (currency, integer amount, period) with a
pure-SQL lakh-grouping formatter. Read-only. Usage: uv run python -I f3_duck_lakh.py DB"""
import re, sqlite3, sys
import duckdb
rows = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).execute("SELECT Salary FROM SalaryDataset").fetchall()
pat = re.compile(r"^(\D+?)([0-9][0-9,]*)/(yr|mo|hr)$")
parts = [(s, *pat.match(s).groups()) for (s,) in rows]
d = duckdb.connect()
d.execute("CREATE TABLE s(src VARCHAR, cur VARCHAR, amt BIGINT, per VARCHAR)")
d.executemany("INSERT INTO s VALUES (?,?,?,?)", [(s, c, int(a.replace(",", "")), p) for s, c, a, p in parts])
# lakh grouping: last 3 digits, then pairs. head = digits[:-3]; pairs from the right of head.
sql = r"""
WITH f AS (SELECT src, cur, per, CAST(amt AS VARCHAR) d FROM s),
g AS (SELECT src, cur, per, d,
  CASE WHEN length(d) <= 3 THEN d
       ELSE regexp_replace(left(d, length(d)-3), '(\d)(?=(\d\d)+$)', '\1,', 'g') || ',' || right(d, 3) END AS grouped FROM f)
SELECT count(*) n, sum((cur || grouped || '/' || per = src)::INT) exact FROM g"""
try:
    print("lookahead regex:", d.execute(sql).fetchone())
except Exception as e:
    print("lookahead regex unsupported:", type(e).__name__, str(e)[:120])
# fallback without lookahead: build groups by reversing
sql2 = r"""
WITH f AS (SELECT src, cur, per, CAST(amt AS VARCHAR) d FROM s),
g AS (SELECT src, cur, per, d, CASE WHEN length(d) <= 3 THEN d ELSE
   reverse(regexp_replace(reverse(left(d, length(d)-3)), '(\d\d)(?=\d)', '\1,', 'g')) || ',' || right(d,3) END grouped FROM f)
SELECT count(*), sum((cur || grouped || '/' || per = src)::INT) FROM g"""
try:
    print("reverse + lookahead:", d.execute(sql2).fetchone())
except Exception as e:
    print("reverse + lookahead unsupported:", type(e).__name__, str(e)[:120])
sql3 = r"""
WITH f AS (SELECT src, cur, per, CAST(amt AS VARCHAR) d FROM s),
g AS (SELECT src, cur, per, CASE WHEN length(d) <= 3 THEN d ELSE
   rtrim(reverse(regexp_replace(reverse(left(d, length(d)-3)), '(\d\d)', '\1,', 'g')), ',') END h, right(d,3) t, length(d) L FROM f),
k AS (SELECT src, cur, per, CASE WHEN L <= 3 THEN h ELSE ltrim(h, ',') || ',' || t END grouped FROM g)
SELECT count(*), sum((cur || grouped || '/' || per = src)::INT) FROM k"""
print("reverse pairs, no lookahead:", d.execute(sql3).fetchone())
