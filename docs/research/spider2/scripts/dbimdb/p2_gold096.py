"""Compare our local096 answer (q5_gold.sql block local096_female_only) with gold/local096_a.csv. Read-only.
Usage: python3 -I p2_gold096.py data/spider2/Db-IMDB.sqlite docs/research/spider2/scripts/dbimdb"""
import csv, sqlite3, sys, os

db, here = sys.argv[1], sys.argv[2]
sql = open(os.path.join(here, "q5_gold.sql")).read().split("-- name: local096_female_only")[1].split("-- name:")[0]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
ours = {r[0]: (r[1], r[2]) for r in con.execute(sql)}
gold = {int(r["YEAR"]): (int(r["TOTAL_MOVIES"]), float(r["PERCENTAGE_EXCLUSIVELY_FEMALE"])) for r in csv.DictReader(open(os.path.join(here, "gold/local096_a.csv")))}
print("years ours/gold:", len(ours), len(gold))
diff = [(y, ours.get(y), gold.get(y)) for y in sorted(set(ours) | set(gold)) if ours.get(y) != gold.get(y)]
print("differing years:", len(diff))
for d in diff[:20]: print(d)
print("gold years with pct > 0:", [(y, v) for y, v in sorted(gold.items()) if v[1] > 0])
