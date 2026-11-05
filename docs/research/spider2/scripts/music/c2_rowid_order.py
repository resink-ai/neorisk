"""Is each music table stored in the same physical (rowid) order as its chinook twin? Read-only.
Also: do the sqlite_sequence values in chinook equal music's max ids (so a music build needs no sequence)?
Usage: python3 -I c2_rowid_order.py MUSIC_DB CHINOOK_DB"""
import sqlite3, sys
m, c = (sqlite3.connect(f"file:{p}?mode=ro", uri=True) for p in sys.argv[1:3])
pairs = [("Artist", "artists"), ("Album", "albums"), ("Genre", "genres"), ("MediaType", "media_types"),
         ("Track", "tracks"), ("Playlist", "playlists"), ("PlaylistTrack", "playlist_track"),
         ("Employee", "employees"), ("Customer", "customers"), ("Invoice", "invoices"), ("InvoiceLine", "invoice_items")]
for a, b in pairs:
    ra = m.execute(f"select * from [{a}] order by rowid").fetchall()
    rb = c.execute(f"select * from [{b}] order by rowid").fetchall()
    print(f"{a:<14} same rowid order: {ra == rb}   same rowids: {[r[0] for r in m.execute(f'select rowid from [{a}] order by rowid')] == [r[0] for r in c.execute(f'select rowid from [{b}] order by rowid')]}")
print("music sqlite_* tables:", [r[0] for r in m.execute("select name from sqlite_master where name like 'sqlite_%'")])
print("chinook sqlite_* tables:", [r[0] for r in c.execute("select name from sqlite_master where name like 'sqlite_%'")])
print("music indexes:", m.execute("select count(*) from sqlite_master where type='index' and sql is not null").fetchone()[0],
      " chinook indexes:", c.execute("select count(*) from sqlite_master where type='index' and sql is not null").fetchone()[0])
print("music DDL has AUTOINCREMENT:", any('AUTOINCREMENT' in (r[0] or '').upper() for r in m.execute("select sql from sqlite_master")))
print("chinook DDL has AUTOINCREMENT:", any('AUTOINCREMENT' in (r[0] or '').upper() for r in c.execute("select sql from sqlite_master")))
