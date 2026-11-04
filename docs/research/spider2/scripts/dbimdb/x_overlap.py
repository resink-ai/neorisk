"""Do Db-IMDB and imdb_movies overlap? Compares movie ids, person ids, titles, years, ratings. Read-only.
Usage: python3 -I x_overlap.py data/spider2/Db-IMDB.sqlite data/spider2/imdb_movies.sqlite"""
import sqlite3, sys

a = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
b = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
am = {r[0]: r[1:] for r in a.execute("select MID, title, substr(year,-4), rating, num_votes from Movie")}
bm = {r[0]: r[1:] for r in b.execute("select m.id, m.title, m.year, r.avg_rating, r.total_votes from movies m left join ratings r on r.movie_id = m.id")}
common = set(am) & set(bm)
print("movies: Db-IMDB", len(am), "imdb_movies", len(bm), "common ids", len(common))
print("same title", sum(am[k][0] == bm[k][0] for k in common), "same year", sum(str(am[k][1]) == str(bm[k][1]) for k in common),
      "same rating", sum(am[k][2] == bm[k][2] for k in common), "same votes", sum(am[k][3] == bm[k][3] for k in common))
for k in sorted(common)[:10]: print(" ", k, am[k], bm[k])
ay = {}
for v in am.values(): ay[v[1]] = ay.get(v[1], 0) + 1
print("Db-IMDB movies with year 2017-2019:", sum(c for y, c in ay.items() if y in ("2017", "2018", "2019")))
at = {(v[0], v[1]) for v in am.values()}
bt = {(v[0], str(v[1])) for v in bm.values()}
print("common (title, year) pairs:", len(at & bt))
ap = {r[0] for r in a.execute("select distinct PID from Person where PID is not null")}
bp = {r[0] for r in b.execute("select distinct id from names")}
print("persons: Db-IMDB", len(ap), "imdb_movies", len(bp), "common ids", len(ap & bp))
an = {r[0]: r[1] for r in a.execute("select PID, trim(Name) from Person where PID is not null")}
bn = {r[0]: r[1] for r in b.execute("select id, name from names")}
cp = ap & bp
print("common persons with same name:", sum(an[k] == bn[k] for k in cp))
# credits on common movies
ac = {(r[0], r[1]) for r in a.execute("select MID, trim(PID) from M_Cast where PID is not null")}
bc = {(r[0], r[1]) for r in b.execute("select movie_id, name_id from role_mapping")}
print("cast pairs on common movies: Db-IMDB", sum(1 for x in ac if x[0] in common), "imdb_movies", sum(1 for x in bc if x[0] in common), "shared", len({x for x in ac & bc}))
print("common movies where imdb_movies votes > Db-IMDB votes:", sum(1 for k in common if bm[k][3] is not None and bm[k][3] > am[k][3]),
      "<:", sum(1 for k in common if bm[k][3] is not None and bm[k][3] < am[k][3]))
print("max Db-IMDB year of common movies vs imdb_movies year differs:", sum(1 for k in common if str(am[k][1]) != str(bm[k][1])))
