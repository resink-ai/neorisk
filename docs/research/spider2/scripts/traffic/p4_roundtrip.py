"""Round-trip probes for the risky encodings, in Python and in DuckDB (the build engine).
1. every REAL cell of all 4 tables -> JSON number (Python shortest repr) -> DuckDB json_transform DOUBLE == source
2. case_id -> owner text printf('%.0f') (SQLite) -> DuckDB CAST(.. AS DOUBLE) == source
3. collision_date + collision_time -> event_time (UTC, time NULL -> 00:00:00 + flag) -> strftime back == source
4. process_date -> event_time -> strftime back == source
5. 2001 date-coded case_id -> decoded timestamp (the parties/victims time rule) parses for every row
Usage: uv run --frozen python docs/research/spider2/scripts/traffic/p4_roundtrip.py  (from repo root; DB mode=ro)"""
import json, sqlite3
import duckdb
import polars as pl
DB = "data/spider2/California_Traffic_Collision.sqlite"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
dk = duckdb.connect(); dk.execute("SET TimeZone='UTC'")
T = ["collisions", "case_ids", "parties", "victims"]
# 1. REAL cells through JSON
tot = bad = 0
for t in T:
    for c, decl in [(r[1], r[2]) for r in con.execute(f"pragma table_info({t})")]:
        if decl != "REAL": continue
        vals = [r[0] for r in con.execute(f'select "{c}" from {t} where "{c}" is not null')]
        payload = [json.dumps({"v": v}) for v in vals]
        j = pl.DataFrame({"p": payload}, schema={"p": pl.String})
        back = [r[0] for r in dk.execute("""select json_transform(p, '{"v":"DOUBLE"}').v from j""").fetchall()]
        b = sum(x != y for x, y in zip(vals, back)); tot += len(vals); bad += b
        if b: print(f"  {t}.{c}: {b} differ")
print(f"1. REAL cells via JSON into DuckDB: {tot} cells, {bad} differ")
# 2. case_id owner text
rows = []
for t in T: rows += con.execute(f"select case_id, printf('%.0f', case_id) from {t}").fetchall()
k = pl.DataFrame(rows, schema={"v": pl.Float64, "s": pl.String}, orient="row")
print("2. case_id text -> DuckDB DOUBLE:", dk.execute("select count(*), sum((cast(s as double) = v)::int) from k").fetchone(),
      "| distinct texts:", dk.execute("select count(distinct s), count(distinct v) from k").fetchone())
# 3. collision time
rows = con.execute("select collision_date, collision_time from collisions").fetchall()
c = pl.DataFrame(rows, schema={"d": pl.String, "t": pl.String}, orient="row")
r = dk.execute("""with e as (select d, t, cast(d || 'T' || coalesce(t,'00:00:00') || 'Z' as timestamptz) et, t is not null known from c)
 select count(*), sum((strftime(et, '%Y-%m-%d') = d)::int),
        sum((case when known then strftime(et, '%H:%M:%S') end is not distinct from t)::int) from e""").fetchone()
print("3. collision_date/time via event_time (rows, date ok, time ok):", r)
# 4. process_date
rows = con.execute("select process_date from collisions").fetchall()
pd = pl.DataFrame(rows, schema={"d": pl.String}, orient="row")
print("4. process_date via event_time (rows, ok):", dk.execute("select count(*), sum((strftime(cast(d || 'T00:00:00Z' as timestamptz), '%Y-%m-%d') = d)::int) from pd").fetchone())
# 5. decode 2001 ids
from datetime import datetime
for t in ["parties", "victims", "case_ids", "collisions"]:
    ok = fail = 0
    for (v,) in con.execute(f"select case_id from {t} where case_id >= 1e17"):
        s = str(int(v))[-15:]
        try: datetime.strptime("20" + s[:10], "%Y%m%d%H%M"); ok += 1
        except ValueError: fail += 1
    print(f"5. {t}: date-coded ids decoding to a valid YYMMDDHHMM: {ok}, invalid: {fail}")
# 5b. date part alone (YYMMDD) and the HHMM part separately; what the invalid HHMM look like
from collections import Counter
for t in ["parties", "victims", "case_ids", "collisions"]:
    dok = hok = 0; badhm = Counter()
    for (v,) in con.execute(f"select case_id from {t} where case_id >= 1e17"):
        s = str(int(v))[-15:]
        try: datetime.strptime("20" + s[:6], "%Y%m%d"); dok += 1
        except ValueError: pass
        try: datetime.strptime(s[6:10], "%H%M"); hok += 1
        except ValueError: badhm[s[6:10]] += 1
    print(f"5b. {t}: valid YYMMDD {dok}, valid HHMM {hok}, invalid HHMM top {badhm.most_common(4)}")
# 6. the SQLite printf text that DuckDB's CAST reads back differently
bad = dk.execute("select v, s from k where cast(s as double) <> v limit 3").fetchall()
print("6. printf text DuckDB misreads (value, text, python float(text)==value):", [(repr(v), s, float(s) == v) for v, s in bad])
# 7. printf('%.0f') depends on the SQLite build: injective? reads back exactly in Python?
rows = []
for t in T: rows += con.execute(f"select case_id, printf('%.0f', case_id) from {t}").fetchall()
print("7. sqlite", sqlite3.sqlite_version, "| printf('%.0f'): rows", len(rows), "distinct texts", len({s for _, s in rows}),
      "distinct values", len({v for v, _ in rows}), "python float(text)==value", sum(float(s) == v for v, s in rows),
      "| values > int64 max:", sum(v > 2**63 - 1 for v, _ in rows))
