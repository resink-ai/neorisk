"""Probe: which ranking rule reproduces team_driver_ranks (before/after tdr_overrides).
Usage: python3 -I p3_tdr_probe.py data/spider2/f1.sqlite"""
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
con.create_function("noop", 1, lambda x: x)
tdr = {(y, c, d): r for y, c, d, r in con.execute("select year, constructor_id, driver_id, team_driver_rank from team_driver_ranks")}
ov = {(y, c, d): r for y, c, d, r in con.execute(
    "select o.year, c.constructor_id, d.driver_id, o.team_driver_rank from tdr_overrides o join constructors c using(constructor_ref) join drivers d using(driver_ref)")}
print("overrides", len(ov), "overrides that hit a tdr row", sum(k in tdr for k in ov), "tdr rows equal to override", sum(tdr.get(k) == v for k, v in ov.items()))
# features per (year, constructor, driver)
feat = {}
q = """
with ys as (select ra.year, r.constructor_id, r.driver_id, count(*) races, sum(r.points) pts, min(ra.round) first_round,
            min(r.position_order) best, sum(r.position_order) sumpo, avg(r.position_order) avgpo, min(r.grid) bestgrid
            from results r join races ra using(race_id) group by 1,2,3),
fin as (select ra.year, d.driver_id, d.position, d.points from driver_standings d join races ra using(race_id)
        where ra.round = (select max(r2.round) from races r2 join driver_standings d2 using(race_id) where r2.year = ra.year and d2.driver_id = d.driver_id))
select ys.*, fin.position, fin.points, dr.driver_ref from ys left join fin using(year, driver_id) join drivers dr using(driver_id)"""
for row in con.execute(q):
    y, c, d, races, pts, fr, best, sumpo, avgpo, bestgrid, fpos, fpts, ref = row
    feat[(y, c, d)] = dict(races=races, pts=pts, fr=fr, best=best, avgpo=avgpo, fpos=fpos, fpts=fpts, ref=ref, d=d)
rules = {
  "final standings position asc": lambda f: (f["fpos"] if f["fpos"] is not None else 9999,),
  "final standings position asc, ref": lambda f: (f["fpos"] if f["fpos"] is not None else 9999, f["ref"]),
  "team points desc, races desc": lambda f: (-f["pts"], -f["races"]),
  "team points desc, best finish": lambda f: (-f["pts"], f["best"]),
  "races desc, team points desc": lambda f: (-f["races"], -f["pts"]),
}
from itertools import groupby
for name, key in rules.items():
    groups = {}
    for k, f in feat.items():
        if k in tdr: groups.setdefault(k[:2], []).append((key(f), k))
    pred = {}
    for g, lst in groups.items():
        lst.sort()
        # dense? use row_number
        for i, (_, k) in enumerate(lst, 1): pred[k] = i
    raw_bad = [k for k in tdr if pred[k] != tdr[k]]
    with_ov = [k for k in tdr if ov.get(k, pred[k]) != tdr[k]]
    print(f"{name:40s} mismatch raw {len(raw_bad):5d}  after overrides {len(with_ov):5d}  e.g. {with_ov[:4]}")
