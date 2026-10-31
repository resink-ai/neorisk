"""Column profile of every table: storage classes, NULL / '' / '\\N' counts, distinct values,
min and max. Usage: python3 -I p1_profile.py DB"""
import sqlite3
import sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
for t in tables:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"## {t}  rows={n}")
    for _, c, decl, *_ in con.execute(f'pragma table_info("{t}")'):
        q = f'"{c}"'
        types = con.execute(f'select typeof({q}), count(*) from "{t}" group by 1 order by 1').fetchall()
        nul, emp, bsn, dist = con.execute(
            f"select sum({q} is null), sum({q} = ''), sum({q} = '\\N'), count(distinct {q}) from \"{t}\""
        ).fetchone()
        mn, mx = con.execute(f'select min({q}), max({q}) from "{t}"').fetchone()
        s = lambda v: (repr(v)[:40])
        print(f"  {c:28s} {decl:12s} {dict(types)}  null={nul} empty={emp} \\N={bsn} "
              f"distinct={dist} min={s(mn)} max={s(mx)}")
