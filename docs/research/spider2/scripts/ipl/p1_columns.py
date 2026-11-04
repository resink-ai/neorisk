"""Per-column profile of IPL.sqlite (read-only): storage classes, NULLs, '' , whitespace, distinct, min, max.
Usage: python3 -I p1_columns.py DB"""
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for (t,) in c.execute("select name from sqlite_master where type='table' order by name").fetchall():
    n = c.execute(f"select count(*) from {t}").fetchone()[0]
    print(f"## {t}  rows={n}")
    for col in [r[1] for r in c.execute(f"pragma table_info({t})")]:
        ty = c.execute(f"select group_concat(ty||':'||n,' ') from (select typeof({col}) ty,count(*) n from {t} group by 1)").fetchone()[0]
        e = c.execute(f"select sum({col} is null), sum({col}=''), sum(trim({col})<>{col}), sum({col}='\\N'), count(distinct {col}), min({col}), max({col}) from {t}").fetchone()
        print(f"{col}: types[{ty}] null={e[0]} empty={e[1]} ws={e[2]} backslashN={e[3]} distinct={e[4]} min={e[5]!r} max={e[6]!r}")
