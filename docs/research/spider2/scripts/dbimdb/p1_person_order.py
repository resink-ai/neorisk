"""Is Person's row order (its "index" column) a function of the credit tables?
Tests generator hypotheses for the three Person blocks. Read-only.
Usage: python3 -I p1_person_order.py data/spider2/Db-IMDB.sqlite"""
import sqlite3, sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
person = con.execute('select "index", PID, Name, Gender from Person order by "index"').fetchall()
movies = [r[0] for r in con.execute('select MID from Movie order by "index"')]
mpos = {m: i for i, m in enumerate(movies)}
cast = con.execute('select "index", MID, PID from M_Cast order by "index"').fetchall()
prod = con.execute('select "index", MID, PID from M_Producer order by "index"').fetchall()
dirs = con.execute('select "index", MID, PID from M_Director order by "index"').fetchall()

null_i = [p[0] for p in person if p[1] is None]
print("null row index:", null_i)
A = [p[1] for p in person if p[0] < null_i[0]]
B = [p[1] for p in person if p[0] > null_i[0] and p[2].startswith(" ")]
C = [p[1] for p in person if p[0] > null_i[0] and not p[2].startswith(" ")]
print("blocks A,B,C sizes:", len(A), len(B), len(C))
print("B rows all before C rows:", max(p[0] for p in person if p[1] in set(B) and p[0] > null_i[0] and p[2].startswith(" ")) <
      min(p[0] for p in person if p[0] > null_i[0] and not p[2].startswith(" ")))

def firstseen(seq):
    seen, out = set(), []
    for x in seq:
        if x is None: continue
        x = x.strip()
        if x not in seen:
            seen.add(x); out.append(x)
    return out

cast_fs = firstseen(r[2] for r in cast)
print("H1 A == first len(A) distinct cast PIDs in M_Cast order:", cast_fs[:len(A)] == A)
# where does A stop inside M_Cast?
last_a = A[-1]
stop = next(r for r in cast if r[2] and r[2].strip() == last_a)
print("A's last PID first seen at M_Cast index", stop[0], "movie index", mpos[stop[1]], "of", len(movies))
rest_cast = cast_fs[len(A):]
Aset = set(A)
prod_fs_new = [x for x in firstseen(r[2] for r in prod) if x not in Aset]
# H2: B = remaining cast (first-seen) then producers not yet seen
h2 = firstseen(rest_cast + [x for x in prod_fs_new if x not in set(rest_cast)])
print("H2 B == rest-of-cast then new producers:", h2 == B, len(h2))
# H3: per movie interleaved: for movies from the stop movie on: cast then producer; earlier movies: producers only
by_movie_c, by_movie_p = {}, {}
for r in cast: by_movie_c.setdefault(r[1], []).append(r[2])
for r in prod: by_movie_p.setdefault(r[1], []).append(r[2])
seq = []
for m in movies:
    seq += by_movie_p.get(m, [])
h3a = [x for x in firstseen(seq) if x not in Aset]
print("H3a B == producers first-seen (new only):", h3a == B, len(h3a))
seq = []
for m in movies:
    seq += by_movie_c.get(m, []) + by_movie_p.get(m, [])
h3 = [x for x in firstseen(seq) if x not in Aset]
print("H3 B == per-movie cast+producers first-seen (new only):", h3 == B, len(h3))
seq = []
for m in movies:
    seq += by_movie_p.get(m, []) + by_movie_c.get(m, [])
h4 = [x for x in firstseen(seq) if x not in Aset]
print("H4 B == per-movie producers+cast first-seen (new only):", h4 == B, len(h4))
print("set(B) == set(H3):", set(B) == set(h3), "B - H3:", len(set(B) - set(h3)), "H3 - B:", len(set(h3) - set(B)))
# longest common prefix with each hypothesis
for name, h in (("H2", h2), ("H3a", h3a), ("H3", h3), ("H4", h4)):
    k = 0
    while k < min(len(h), len(B)) and h[k] == B[k]: k += 1
    print(name, "common prefix with B:", k)
dir_fs = firstseen(r[2] for r in dirs)
print("H5 C == distinct directors in M_Director order:", dir_fs == C)
# Names: does the Person name equal some consistent source? B/C dup names differ only by leading space
names = {}
for p in person:
    if p[1]: names.setdefault(p[1], set()).add(p[2])
print("dup PIDs whose names differ only by the leading space:",
      sum(1 for v in names.values() if len(v) == 2 and len({n.strip() for n in v}) == 1), "of", sum(1 for v in names.values() if len(v) > 1))

# H6: the whole table = distinct rows of (cast rows ++ producer rows ++ director rows), NULL kept as a value,
# keyed on (trimmed PID, Name-with-its-space): a pandas drop_duplicates over full rows.
def firstseen_raw(seq):
    seen, out = set(), []
    for x in seq:
        k = None if x is None else x.strip()
        if k not in seen:
            seen.add(k); out.append(k)
    return out
cp = firstseen_raw([r[2] for r in cast] + [r[2] for r in prod])
h6 = cp + dir_fs
print("H6 Person.PID by index == firstseen(cast ++ producer, NULL kept) ++ firstseen(director):",
      h6 == [p[1] for p in person], len(h6), len(person))
print("first NULL in M_Cast at index", next(r[0] for r in cast if r[2] is None))
