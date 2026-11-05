"""Per-column profile of all 4 tables: storage classes, NULL / '' counts, distinct count, min/max, top values.
Usage: python3 -I p1_columns.py   (run from repo root; DB opened mode=ro)"""
import sqlite3
DB = "data/spider2/California_Traffic_Collision.sqlite"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
for t in ["collisions", "case_ids", "parties", "victims"]:
    cols = [(r[1], r[2]) for r in con.execute(f"pragma table_info({t})")]
    n = con.execute(f"select count(*) from {t}").fetchone()[0]
    print(f"## {t}  rows={n}")
    for c, decl in cols:
        q = f'"{c}"'
        types = con.execute(f"select typeof({q}), count(*) from {t} group by 1 order by 2 desc").fetchall()
        empty = con.execute(f"select count(*) from {t} where {q}=''").fetchone()[0]
        nd = con.execute(f"select count(distinct {q}) from {t}").fetchone()[0]
        mn, mx = con.execute(f"select min({q}), max({q}) from {t}").fetchone()
        top = con.execute(f"select {q}, count(*) from {t} group by 1 order by 2 desc limit 6").fetchall()
        tops = "; ".join(f"{v!r}:{k}" for v, k in top)
        print(f"{c} [{decl}] types={dict(types)} empty={empty} distinct={nd} min={mn!r} max={mx!r} top={tops}")
    print()
