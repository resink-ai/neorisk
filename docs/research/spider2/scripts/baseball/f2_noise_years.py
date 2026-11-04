"""Where the 17-digit float noise sits (pitching.baopp, team.fp). Usage: python3 -I f2_noise_years.py DB"""
import sqlite3, sys, collections
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for t, c in (("pitching", "baopp"), ("team", "fp")):
    rows = con.execute(f"select year, {c} from {t} where typeof({c})='real'").fetchall()
    noisy = [(y, x) for y, x in rows if len(repr(x)) > 8]
    by = collections.Counter(y // 10 * 10 for y, _ in noisy)
    vals = collections.Counter(round(x, 6) for _, x in noisy)
    print(f"{t}.{c}: noisy={len(noisy)} of {len(rows)}; by decade={dict(sorted(by.items()))}; distinct noisy values={len(vals)}; top={vals.most_common(5)}")
