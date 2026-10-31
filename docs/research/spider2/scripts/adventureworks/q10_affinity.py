"""Mixed storage classes ('' text in INTEGER/FLOAT columns): can a rebuild that emits a VARCHAR
column (DuckDB has one type per column) restore them through the source DDL's type affinity?
Writes each mixed column as text into an in-memory table built from the source DDL and checks
that value and typeof() come back identical. Usage: python3 -I q10_affinity.py DB"""
import sqlite3
import sys

src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
mem = sqlite3.connect(":memory:")
ddl = dict(src.execute("select name, sql from sqlite_master where type='table'"))
for t, s in ddl.items():
    mem.execute(s)


def as_text(v):
    if v is None:
        return None
    if isinstance(v, float):
        return repr(v)          # shortest round-trip repr, as DuckDB's CAST(double AS VARCHAR)
    return str(v)


total_bad = 0
for t in ddl:
    cols = [r[1] for r in src.execute(f'pragma table_info("{t}")')]
    mixed = [c for c in cols
             if src.execute(f'select count(distinct typeof("{c}")) from "{t}"').fetchone()[0] > 1]
    if not mixed:
        continue
    for c in mixed:
        vals = [r[0] for r in src.execute(f'select "{c}" from "{t}"')]
        mem.execute(f'delete from "{t}"')
        mem.executemany(f'insert into "{t}"("{c}") values (?)', [(as_text(v),) for v in vals])
        got = mem.execute(f'select "{c}", typeof("{c}") from "{t}" order by rowid').fetchall()
        want = src.execute(f'select "{c}", typeof("{c}") from "{t}" order by rowid').fetchall()
        bad = sum(g != w for g, w in zip(got, want))
        total_bad += bad
        decl = [r[2] for r in src.execute(f'pragma table_info("{t}")') if r[1] == c][0]
        print(f"{t}.{c} ({decl}): rows={len(vals)} value+typeof mismatches after text insert = {bad}")

# Every REAL column through text too (worst case: a view that formats all numbers as text)
for t in ddl:
    for _, c, decl, *_ in src.execute(f'pragma table_info("{t}")'):
        vals = [r[0] for r in src.execute(f'select "{c}" from "{t}" where typeof("{c}")=\'real\'')]
        if not vals:
            continue
        mem.execute("create temp table if not exists r(x FLOAT)")
        mem.execute("delete from r")
        mem.executemany("insert into r values (?)", [(repr(v),) for v in vals])
        back = [r[0] for r in mem.execute("select x from r order by rowid")]
        print(f"REAL via text {t}.{c}: {sum(a != b for a, b in zip(back, vals))}/{len(vals)} differ")
print(f"total mismatches in mixed columns: {total_bad}")
