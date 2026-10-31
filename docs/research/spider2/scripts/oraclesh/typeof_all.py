"""Storage class mix, NULL / '' counts and text lengths of every column of every table.
Usage: python3 -I typeof_all.py DB"""
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
for t in tabs:
    cols = con.execute(f'pragma table_info("{t}")').fetchall()
    print(f"## {t}")
    for _, c, decl, *_ in cols:
        mix = con.execute(f'select typeof("{c}"), count(*) from "{t}" group by 1').fetchall()
        e = con.execute(f'select sum("{c}" = \'\'), sum(typeof("{c}")=\'text\' and "{c}" <> trim("{c}")), '
                        f'min(length("{c}")), max(length("{c}")), count(distinct "{c}") from "{t}"').fetchone()
        print(f"  {c:26s} {decl:10s} {dict(mix)}  empty={e[0]} padded={e[1]} len={e[2]}..{e[3]} distinct={e[4]}")
