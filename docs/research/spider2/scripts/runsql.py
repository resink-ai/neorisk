"""Run a .sql file of named queries (`-- name: <label>` headers) read-only and print results.

Usage: python3 -I runsql.py <queries.sql> [db ...]
The first db is opened as `main` (read-only); others are ATTACHed read-only as e, x.
"""
import sqlite3
import sys
import time

DB_DIR = "data/spider2/"


def main():
    sqlfile = sys.argv[1]
    dbs = sys.argv[2:] or ["Brazilian_E_Commerce"]
    con = sqlite3.connect(f"file:{DB_DIR}{dbs[0]}.sqlite?mode=ro", uri=True)
    for alias, name in zip(("e", "x"), dbs[1:]):
        con.execute(f"ATTACH DATABASE 'file:{DB_DIR}{name}.sqlite?mode=ro' AS {alias}")
    text = open(sqlfile).read()
    blocks = [b for b in text.split("-- name:") if b.strip()]
    for b in blocks:
        label, _, sql = b.partition("\n")
        sql = sql.strip()
        if not sql:
            continue
        t0 = time.time()
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        print(f"### {label.strip()}  ({len(rows)} rows, {time.time()-t0:.1f}s)")
        print(" | ".join(cols))
        for r in rows[:200]:
            print(" | ".join("NULL" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v)) for v in r))
        print(flush=True)


if __name__ == "__main__":
    main()
