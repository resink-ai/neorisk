"""Run chinook's ingest blocks (datasets/chinook/specs/ingest.sql, read only) on chinook.sqlite, and the same
blocks with the 11 source table names renamed on music.sqlite. Compare every block's output as an ordered list
(the ingest's ORDER BY fixes the order), with storage classes. Equal outputs => the same event log.
Usage: python3 -I c3_ingest_same_log.py INGEST_SQL MUSIC_DB CHINOOK_DB"""
import re, sqlite3, sys
ingest, mdb, cdb = sys.argv[1:4]
m, c = (sqlite3.connect(f"file:{p}?mode=ro", uri=True) for p in (mdb, cdb))
ren = {"genres": "Genre", "media_types": "MediaType", "artists": "Artist", "albums": "Album", "tracks": "Track",
       "playlists": "Playlist", "playlist_track": "PlaylistTrack", "employees": "Employee", "customers": "Customer",
       "invoices": "Invoice", "invoice_items": "InvoiceLine"}
text = open(ingest, encoding="utf-8").read()
blocks = re.split(r"^(-- (?:entity|event): .*)$", text, flags=re.M)[1:]
total = 0
for head, sql in zip(blocks[0::2], blocks[1::2]):
    msql = re.sub(r"\b(FROM|JOIN)\s+(" + "|".join(ren) + r")\b", lambda x: f"{x.group(1)} {ren[x.group(2)]}", sql)
    a = c.execute(sql).fetchall(); b = m.execute(msql).fetchall()
    same = [tuple((type(v).__name__, v) for v in r) for r in a] == [tuple((type(v).__name__, v) for v in r) for r in b]
    total += len(a)
    print(f"{head:<70} rows chinook {len(a):>5}  music {len(b):>5}  identical (ordered, typed): {same}")
print("rows compared:", total)
