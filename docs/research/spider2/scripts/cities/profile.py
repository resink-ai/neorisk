"""Column profile of a set of tables: row count, rowid range, and per column the storage
classes (typeof), NULL / '' / '\\N' counts, distinct count, min and max, leading/trailing space count.
Usage: python3 -I profile.py DB table [table ...]   (opened with mode=ro, never written)"""
import sqlite3, sys

db, tables = sys.argv[1], sys.argv[2:]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
for t in tables:
    n, lo, hi = con.execute(f'select count(*), min(rowid), max(rowid) from "{t}"').fetchone()
    print(f"### {t}: {n} rows, rowid {lo}..{hi}")
    cols = [(r[1], r[2]) for r in con.execute(f'pragma table_info("{t}")')]
    print("column | decl | typeof counts | null | empty | \\N | distinct | min | max | ws-padded")
    for c, decl in cols:
        q = f'"{c}"'
        ty = con.execute(f'select typeof({q}), count(*) from "{t}" group by 1 order by 2 desc').fetchall()
        nul, emp, bn, ws = con.execute(
            f"select sum({q} is null), sum({q} = ''), sum({q} = '\\N'), "
            f"sum(typeof({q})='text' and {q} <> trim({q})) from \"{t}\"").fetchone()
        dist = con.execute(f'select count(distinct {q}) from "{t}"').fetchone()[0]
        mn, mx = con.execute(f'select min({q}), max({q}) from "{t}" where {q} is not null and {q} <> \'\'').fetchone()
        def s(x):
            x = repr(x)
            return x if len(x) < 40 else x[:37] + "..."
        print(f"{c} | {decl} | {dict(ty)} | {nul} | {emp} | {bn} | {dist} | {s(mn)} | {s(mx)} | {ws}")
    print()
