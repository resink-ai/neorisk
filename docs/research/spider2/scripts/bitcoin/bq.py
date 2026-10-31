"""Run named SQL blocks read-only against the bitcoin_* tables of bank_sales_trading.sqlite.

Usage: python3 -I bq.py DB QUERYFILE [names...]   (blocks separated by lines '-- name: X')

The three bitcoin_* tables are copied into an in-memory SQLite; the source file is opened with
mode=ro and never written. Helper views (in memory only):
  tx  = bitcoin_transactions + d (ISO date from txn_date DD-MM-YYYY)
  pr  = bitcoin_prices + d (ISO date) + vol (volume parsed: K=1e3, M=1e6, '-'=NULL)
        + chg (change parsed, percent as REAL)
"""
import sqlite3, sys, time

db, qf = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con = sqlite3.connect(":memory:")
for t in ("bitcoin_members", "bitcoin_transactions", "bitcoin_prices"):
    ddl = src.execute("select sql from sqlite_master where name=?", (t,)).fetchone()[0]
    con.execute(ddl)
    rows = src.execute(f'select * from "{t}" order by rowid').fetchall()
    con.executemany(f'insert into "{t}" values ({",".join("?" * len(rows[0]))})', rows)
src.close()
con.executescript("""
create view tx as select rowid as rid, *, substr(txn_date,7,4)||'-'||substr(txn_date,4,2)||'-'||substr(txn_date,1,2) as d
  from bitcoin_transactions;
create view pr as select rowid as rid, *, substr(market_date,7,4)||'-'||substr(market_date,4,2)||'-'||substr(market_date,1,2) as d,
  case when volume='-' then null
       when volume like '%K' then cast(substr(volume,1,length(volume)-1) as real)*1e3
       when volume like '%M' then cast(substr(volume,1,length(volume)-1) as real)*1e6 end as vol,
  cast(substr(change,1,length(change)-1) as real) as chg
  from bitcoin_prices;
create index i_tx on bitcoin_transactions(ticker, txn_date);
create index i_pr on bitcoin_prices(ticker, market_date);
""")
blocks, name, buf = [], None, []
for line in open(qf, encoding="utf-8"):
    if line.startswith("-- name:"):
        if name: blocks.append((name, "".join(buf)))
        name, buf = line.split(":", 1)[1].strip(), []
    else:
        buf.append(line)
if name: blocks.append((name, "".join(buf)))
only = set(sys.argv[3:])
for name, sql in blocks:
    if only and name not in only: continue
    t = time.time()
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"### {name}  ({len(rows)} rows, {time.time()-t:.2f}s)")
    print(" | ".join(cols))
    for r in rows[:80]:
        print(" | ".join(str(x) for x in r))
    print(flush=True)
