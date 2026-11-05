"""Shapes to fit for stage 2 on stacking.sqlite.

Run: python3 -I docs/research/spider2/scripts/stacking/05_dists.py
"""
import sqlite3
import statistics as st
from collections import Counter

con = sqlite3.connect("file:data/spider2/stacking.sqlite?mode=ro", uri=True)


def q(xs, ps=(0, 0.1, 0.25, 0.5, 0.75, 0.9, 1)):
    xs = sorted(xs)
    return {p: round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], 4) for p in ps}


print("versions per problem", sorted(Counter(n for (n,) in con.execute("SELECT count(*) FROM solution GROUP BY name")).items()))
print("problem types", con.execute("SELECT type, count(*) FROM problem GROUP BY 1").fetchall())
print("eda features per run", q([n for (n,) in con.execute("SELECT count(*) FROM eda GROUP BY name, version")]))
print("step-1 base models per run", q([n for (n,) in con.execute("SELECT count(*) FROM model_score WHERE step=1 AND model<>'Stack' GROUP BY name, version")]))
print("step-2 base models per run", q([n for (n,) in con.execute("SELECT count(*) FROM model_score WHERE step=2 AND model<>'Stack' GROUP BY name, version")]))
for t in ("classification", "regression"):
    for step in (1, 3):
        xs = [r[0] for r in con.execute(
            "SELECT m.test_score FROM model_score m JOIN problem p ON p.name=m.name WHERE p.type=? AND m.step=? AND m.model='Stack'", (t, step))]
        print(f"Stack test_score {t} step {step}: n={len(xs)} {q(xs)}")
    xs = [r[0] for r in con.execute(
        "SELECT m.train_score - m.test_score FROM model_score m JOIN problem p ON p.name=m.name WHERE p.type=? AND m.model<>'Stack' AND m.test_score>-1", (t,))]
    print(f"train-test gap (base models, test>-1) {t}: {q(xs)}")
# version-to-version: does the Stack step-3 test score improve with version?
rows = con.execute("SELECT name, version, test_score FROM model_score WHERE model='Stack' AND step=3 ORDER BY name, version").fetchall()
up = down = same = 0
for a, b in zip(rows, rows[1:]):
    if a[0] == b[0]:
        up += b[2] > a[2]; down += b[2] < a[2]; same += b[2] == a[2]
print("Stack step-3 score, version v+1 vs v: up", up, "down", down, "same", same)
# L1_model switches between consecutive versions
rows = con.execute("SELECT DISTINCT name, version, L1_model FROM model ORDER BY name, version").fetchall()
sw = sum(1 for a, b in zip(rows, rows[1:]) if a[0] == b[0] and a[2] != b[2])
print("L1_model switches between consecutive versions:", sw, "of", sum(1 for a, b in zip(rows, rows[1:]) if a[0] == b[0]))
print("first version L1_model:", Counter(r[2] for r in rows if r[1] == 1))
# solution config changes between consecutive versions
rows = con.execute("SELECT name, version, nb_model, nb_feature, score, test_size, resampling FROM solution ORDER BY name, version").fetchall()
ch = Counter()
for a, b in zip(rows, rows[1:]):
    if a[0] == b[0]:
        for i, c in enumerate(("nb_model", "nb_feature", "score", "test_size", "resampling"), 2):
            ch[c] += a[i] != b[i]
print("config fields changed between consecutive versions:", dict(ch))
