"""Measure music.sqlite against chinook.sqlite table by table, read-only.
Usage: python3 -I c1_equivalence.py MUSIC_DB CHINOOK_DB
For each table pair: row counts, column names, per-column storage classes, and the multiset
difference of rows under two comparisons: (a) the contract's (numbers by value, text byte-exact,
NULL only = NULL) and (b) strict (storage class + value)."""
import sqlite3, sys
from collections import Counter
music, chin = (sqlite3.connect(f"file:{p}?mode=ro", uri=True) for p in sys.argv[1:3])
pairs = [("Artist", "artists"), ("Album", "albums"), ("Genre", "genres"), ("MediaType", "media_types"),
         ("Track", "tracks"), ("Playlist", "playlists"), ("PlaylistTrack", "playlist_track"),
         ("Employee", "employees"), ("Customer", "customers"), ("Invoice", "invoices"), ("InvoiceLine", "invoice_items")]
mt = {r[0] for r in music.execute("select name from sqlite_master where type='table'")}
ct = {r[0] for r in chin.execute("select name from sqlite_master where type='table'")}
print("music tables not paired:", sorted(mt - {a for a, _ in pairs}))
print("chinook tables not paired:", sorted(ct - {b for _, b in pairs}))
def cols(con, t): return [(r[1], r[2]) for r in con.execute(f'pragma table_info("{t}")')]
def contract(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool): return ("num", float(v))
    return (type(v).__name__, v)
def strict(v): return (type(v).__name__, v)
tot_a = tot_s = 0
for a, b in pairs:
    ca, cb = cols(music, a), cols(chin, b)
    na = [c for c, _ in ca]; nb = [c for c, _ in cb]
    print(f"\n## {a} vs {b}: rows {music.execute(f'select count(*) from [{a}]').fetchone()[0]} vs {chin.execute(f'select count(*) from [{b}]').fetchone()[0]}")
    print(f"   same column names in order: {na == nb}" + ("" if na == nb else f"  music={na} chinook={nb}"))
    decl_diff = [(x, dx, dy) for (x, dx), (_, dy) in zip(ca, cb) if dx != dy]
    if decl_diff: print(f"   declared types differ: {decl_diff}")
    for c in na:
        sa = dict(music.execute(f'select typeof([{c}]), count(*) from [{a}] group by 1').fetchall())
        sb = dict(chin.execute(f'select typeof([{c}]), count(*) from [{b}] group by 1').fetchall())
        if sa != sb: print(f"   storage classes differ in {c}: music={sa} chinook={sb}")
    ra = music.execute(f'select {",".join("["+c+"]" for c in na)} from [{a}]').fetchall()
    rb = chin.execute(f'select {",".join("["+c+"]" for c in na)} from [{b}]').fetchall()
    for name, f in (("contract", contract), ("strict", strict)):
        A = Counter(tuple(f(v) for v in r) for r in ra); B = Counter(tuple(f(v) for v in r) for r in rb)
        d1, d2 = sum((A - B).values()), sum((B - A).values())
        print(f"   {name}: rows only in music {d1}, only in chinook {d2}")
        if name == "contract": tot_a += d1 + d2
        else: tot_s += d1 + d2
        for k in list((A - B))[:3]: print("     e.g. music:", k)
        for k in list((B - A))[:3]: print("     e.g. chinook:", k)
print(f"\nTOTAL differing rows: contract {tot_a}, strict {tot_s}")
