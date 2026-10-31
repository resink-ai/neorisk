"""Prototype round trip for the bitcoin_* tables: tables -> events/entities -> tables (DuckDB views).

Run from the repo: uv run --no-sync python -I docs/research/spider2/scripts/bitcoin/p1_roundtrip.py DB

Source opened read-only (mode=ro). Mirrors what specs/ingest.sql + specs/views.sql would do:
  entities members(ext_id, first_name, region), tickers(ext_id)
  event price_published owner=ticker   at market_date 00:00 UTC: price, open, high, low,
                                        volume (i64 units, NULL for '-'), change_pct (f64)
  event trade owner=member ord=txn_id   at txn_time (ms, UTC): ticker, txn_type, quantity,
                                        percentage_fee, txn_id
Then rebuilds the three tables in DuckDB with format rules and compares as multisets, numbers by
value, text byte-exact. Also tests the alternative "volume/change kept as text" and the rule
"txn_id = rank of (event_time, ord)".
"""
import sqlite3, sys
from collections import Counter
from datetime import datetime, timezone
import duckdb

db = sys.argv[1]
src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
M = src.execute("select member_id, first_name, region from bitcoin_members order by rowid").fetchall()
T = src.execute("select txn_id, member_id, ticker, txn_date, txn_type, quantity, percentage_fee, txn_time "
                "from bitcoin_transactions order by rowid").fetchall()
P = src.execute("select ticker, market_date, price, open, high, low, volume, change "
                "from bitcoin_prices order by rowid").fetchall()
src.close()

# ---- ingest (tables -> log) -------------------------------------------------------------
def parse_vol(v):
    if v == "-":
        return None
    mant, suf = v[:-1], v[-1]
    whole, frac = mant.split(".")
    units = int(whole + frac.ljust(2, "0"))          # exact: mantissa has 2 decimals
    return units * (10 if suf == "K" else 10_000)

def parse_chg(c):
    return float(c[:-1])

members = [(i + 1, m[0], m[1], m[2]) for i, m in enumerate(sorted(M))]      # key = rank of ext_id
mkey = {m[1]: m[0] for m in members}
tickers = [(1, "BTC"), (2, "ETH")]
tkey = {t[1]: t[0] for t in tickers}

def iso_ms(s):   # '2017-01-01T00:00:00.000Z' -> aware datetime
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)

price_ev = [(datetime.strptime(p[1], "%d-%m-%Y").replace(tzinfo=timezone.utc), tkey[p[0]],
             p[2], p[3], p[4], p[5], parse_vol(p[6]), parse_chg(p[7]), p[6], p[7]) for p in P]
trade_ev = [(iso_ms(t[7]), mkey[t[1]], tkey[t[2]], t[4], t[5], t[6], t[0]) for t in T]

con = duckdb.connect()
con.execute("set timezone='UTC'")
con.execute("create table members(member_id bigint, ext_id varchar, first_name varchar, region varchar)")
con.executemany("insert into members values (?,?,?,?)", members)
con.execute("create table tickers(ticker_id bigint, ext_id varchar)")
con.executemany("insert into tickers values (?,?)", tickers)
con.execute("create table price_published(event_time timestamptz, ticker_id bigint, price double, open double,"
            " high double, low double, volume bigint, change_pct double, volume_text varchar, change_text varchar)")
con.executemany("insert into price_published values (?,?,?,?,?,?,?,?,?,?)", price_ev)
con.execute("create table trade(event_time timestamptz, member_id bigint, ticker_id bigint, txn_type varchar,"
            " quantity double, percentage_fee double, txn_id bigint)")
con.executemany("insert into trade values (?,?,?,?,?,?,?)", trade_ev)

# ---- views (log -> tables) --------------------------------------------------------------
V = {
 "bitcoin_members": "select ext_id as member_id, first_name, region from members",
 "bitcoin_transactions": """
   select t.txn_id, m.ext_id as member_id, k.ext_id as ticker,
          strftime(t.event_time at time zone 'UTC', '%d-%m-%Y') as txn_date, t.txn_type,
          t.quantity, t.percentage_fee,
          strftime(t.event_time at time zone 'UTC', '%Y-%m-%dT%H:%M:%S.%gZ') as txn_time
   from trade t join members m using (member_id) join tickers k using (ticker_id)""",
 "bitcoin_prices": """
   select k.ext_id as ticker, strftime(p.event_time at time zone 'UTC', '%d-%m-%Y') as market_date,
          p.price, p.open, p.high, p.low,
          case when p.volume is null then '-'
               when p.volume >= 1000000 then printf('%.2fM', p.volume / 1e6)
               else printf('%.2fK', p.volume / 1e3) end as volume,
          printf('%.2f%%', p.change_pct) as change
   from price_published p join tickers k using (ticker_id)""",
 "bitcoin_prices[text]": """
   select k.ext_id, strftime(p.event_time at time zone 'UTC', '%d-%m-%Y'), p.price, p.open, p.high, p.low,
          p.volume_text, p.change_text from price_published p join tickers k using (ticker_id)""",
 "bitcoin_transactions[txn_id=rank]": """
   select row_number() over (order by t.event_time, t.txn_id) as txn_id, m.ext_id, k.ext_id,
          strftime(t.event_time at time zone 'UTC', '%d-%m-%Y'), t.txn_type, t.quantity, t.percentage_fee,
          strftime(t.event_time at time zone 'UTC', '%Y-%m-%dT%H:%M:%S.%gZ')
   from trade t join members m using (member_id) join tickers k using (ticker_id)""",
}
SRC = {"bitcoin_members": M, "bitcoin_transactions": T, "bitcoin_prices": P,
       "bitcoin_prices[text]": P, "bitcoin_transactions[txn_id=rank]": T}

def norm(row):  # INTEGER and REAL by value; text exact; NULL distinct
    return tuple(("n", float(x)) if isinstance(x, (int, float)) and not isinstance(x, bool) else ("t", x) for x in row)

ok_all = True
for name, sql in V.items():
    rebuilt = con.execute(sql).fetchall()
    a, b = Counter(map(norm, SRC[name])), Counter(map(norm, rebuilt))
    ok = a == b
    ok_all &= ok
    print(f"{name:38s} source={len(SRC[name]):6d} rebuilt={len(rebuilt):6d} multiset_equal={ok}")
    if not ok:
        for r in list((a - b).elements())[:3]: print("   only in source :", r)
        for r in list((b - a).elements())[:3]: print("   only in rebuilt:", r)

# ---- per-rule checks -------------------------------------------------------------------
print("volume parsed to exact integer coins (mantissa has 2 decimals):", all(e[6] is None or isinstance(e[6], int) for e in price_ev))
py_fmt = sum((("-" if v is None else (f"{v/1e6:.2f}M" if v >= 1_000_000 else f"{v/1e3:.2f}K")) == vt)
             for *_, v, _c, vt, _ct in [(e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7], e[8], e[9]) for e in price_ev])
print(f"python volume format rule exact: {py_fmt}/{len(price_ev)}")
print(f"python change format '%.2f%%' exact: {sum(f'{e[7]:.2f}%' == e[9] for e in price_ev)}/{len(price_ev)}")
n_ev = len(price_ev) + len(trade_ev)
print(f"events: price_published={len(price_ev)} trade={len(trade_ev)} total={n_ev}; entities: members={len(members)} tickers={len(tickers)}")
print("ALL EXACT:", ok_all)
