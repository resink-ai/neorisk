"""Per-column storage profile of every table: typeof() counts, NULLs, '' and '\\N', min/max,
text length, leading/trailing whitespace. Read-only.
Usage: python3 -I p1_profile.py data/spider2/EU_soccer.sqlite"""
import sqlite3, sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro&immutable=1", uri=True)
tables = [r[0] for r in con.execute(
    "select name from sqlite_master where type='table' order by name")]
print("objects:", con.execute("select group_concat(type||':'||name, ', ') from sqlite_master").fetchone()[0])
for t in tables:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    cols = con.execute(f'pragma table_info("{t}")').fetchall()
    print(f"\n## {t}  rows={n}")
    print("col | decl | typeof counts | null | '' | '\\N' | ws-padded | min | max | len min..max")
    for c in cols:
        name, decl = c[1], c[2]
        q = f'"{name}"'
        types = con.execute(f'select typeof({q}), count(*) from "{t}" group by 1 order by 1').fetchall()
        ts = ",".join(f"{a}:{b}" for a, b in types)
        nul, emp, bsn, ws = con.execute(
            f"select sum({q} is null), sum({q}=''), sum({q}='\\N'), "
            f"sum(typeof({q})='text' and ({q}<>trim({q}))) from \"{t}\"").fetchone()
        mn, mx = con.execute(f'select min({q}), max({q}) from "{t}"').fetchone()
        lmn, lmx = con.execute(f'select min(length({q})), max(length({q})) from "{t}" where typeof({q})=\'text\'').fetchone()
        short = lambda v: (repr(v)[:40] if isinstance(v, str) else v)
        print(f"{name} | {decl} | {ts} | {nul} | {emp} | {bsn} | {ws} | {short(mn)} | {short(mx)} | {lmn}..{lmx}")
