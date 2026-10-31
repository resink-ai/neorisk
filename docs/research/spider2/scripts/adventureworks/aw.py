"""Run named SQL blocks read-only against AdventureWorks.sqlite and print the results.

Usage: python3 -I aw.py DB QUERYFILE [names...]   (blocks start with a line '-- name: X')

The source is opened with mode=ro and copied into an in-memory database, which gets indexes
(the file has none). The file itself is never written.
"""
import sqlite3
import sys
import time


def connect(db):
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con = sqlite3.connect(":memory:")
    src.backup(con)
    src.close()
    for ddl in ("create index i_d_o on salesorderdetail(salesorderid)",
                "create index i_d_p on salesorderdetail(productid)",
                "create index i_h_o on salesorderheader(salesorderid)",
                "create index i_h_sp on salesorderheader(salespersonid)",
                "create index i_p on product(productid)",
                "create index i_cr on currencyrate(currencyrateid)",
                "create index i_cr2 on currencyrate(tocurrencycode, currencyratedate)"):
        con.execute(ddl)
    return con


def blocks(path):
    out, name, buf = [], None, []
    for line in open(path, encoding="utf-8"):
        if line.startswith("-- name:"):
            if name:
                out.append((name, "".join(buf)))
            name, buf = line.split(":", 1)[1].strip(), []
        else:
            buf.append(line)
    if name:
        out.append((name, "".join(buf)))
    return out


if __name__ == "__main__":
    db, qf = sys.argv[1], sys.argv[2]
    only = set(sys.argv[3:])
    con = connect(db)
    for name, sql in blocks(qf):
        if only and name not in only:
            continue
        t = time.time()
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"### {name}  ({len(rows)} rows, {time.time() - t:.1f}s)")
        print(" | ".join(cols))
        for r in rows[:80]:
            print(" | ".join(repr(x) if isinstance(x, float) else str(x) for x in r))
        print()
