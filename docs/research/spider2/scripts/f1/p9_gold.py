"""Reproduce Spider2 gold answers for f1 questions and compare with gold/*.csv.
Usage: python3 -I p9_gold.py data/spider2/f1.sqlite"""
import sqlite3, sys, csv, os
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
G = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gold")
def gold(name): return [r for r in csv.reader(open(os.path.join(G, name)))][1:]
def norm(rows): return [[("" if v is None else (f"{float(v):.4f}" if isinstance(v, float) else str(v))) for v in r] for r in rows]
def normg(rows): return [[(f"{float(v):.4f}" if v.replace('.', '', 1).isdigit() and '.' in v else v) for v in r] for r in rows]
def cmp(label, rows, gfile, ordered=True):
    a, b = norm(rows), normg(gold(gfile))
    ok = a == b if ordered else sorted(a) == sorted(b)
    print(f"{label}: {len(a)} rows vs gold {gfile} {len(b)} rows -> {'MATCH' if ok else 'DIFFER'}")
    if not ok:
        for x, y in list(zip(a, b))[:5]:
            if x != y: print("   ours", x, "gold", y)
    return ok
# local309: the published gold SQL, verbatim
cmp("local309 (gold SQL)", con.execute(open(os.path.join(G, "local309.sql")).read()).fetchall(), "local309_c.csv")
q309 = """with dp as (select ra.year, r.driver_id, sum(r.points) p from results r join races ra using(race_id) group by 1,2),
 cp as (select ra.year, r.constructor_id, sum(r.points) p from results r join races ra using(race_id) group by 1,2),
 bd as (select year, driver_id from dp d where p = (select max(p) from dp d2 where d2.year = d.year)),
 bc as (select year, constructor_id from cp c where p = (select max(p) from cp c2 where c2.year = c.year))
select bd.year, dr.forename || ' ' || dr.surname, c.name from bd join bc using(year) join drivers dr using(driver_id) join constructors c using(constructor_id) order by 1, 2, 3"""
cmp("local309 (results-sum rewrite, driver+constructor)", con.execute(q309).fetchall(), "local309_a.csv")
q310 = """with dp as (select ra.year, r.driver_id, sum(r.points) p from results r join races ra using(race_id) group by 1,2),
 cp as (select ra.year, r.constructor_id, sum(r.points) p from results r join races ra using(race_id) group by 1,2)
select y.year from (select year, (select max(p) from dp where dp.year = s.year) + (select max(p) from cp where cp.year = s.year) t from seasons s) y
where t is not null order by t limit 3"""
cmp("local310", con.execute(q310).fetchall(), "local310_a.csv")
q311 = """with fin as (select ra.year, max(ra.round) r from races ra join constructor_standings using(race_id) group by 1),
 cs as (select ra.year, cs.constructor_id, cs.points from constructor_standings cs join races ra using(race_id) join fin on fin.year = ra.year and fin.r = ra.round),
 dp as (select ra.year, r.constructor_id, r.driver_id, sum(r.points) p from (select race_id, driver_id, constructor_id, points from results union all select race_id, driver_id, constructor_id, points from sprint_results) r join races ra using(race_id) group by 1,2,3),
 best as (select year, constructor_id, max(p) p from dp group by 1,2)
select c.name, cs.year from cs join best using(year, constructor_id) join constructors c using(constructor_id) order by cs.points + best.p desc limit 3"""
cmp("local311 (final constructor standings + best driver, sprints included)", con.execute(q311).fetchall(), "local311_a.csv")
q335 = """with dp as (select ra.year, r.driver_id, sum(r.points) p from results r join races ra using(race_id) where ra.year >= 2001 group by 1,2 having sum(r.points) > 0),
 mn as (select year, driver_id from dp d where p = (select min(p) from dp d2 where d2.year = d.year)),
 dc as (select distinct mn.year, r.constructor_id from mn join results r on r.driver_id = mn.driver_id join races ra on ra.race_id = r.race_id and ra.year = mn.year)
select c.name, count(*) n from dc join constructors c using(constructor_id) group by 1 order by 2 desc, 1 limit 5"""
cmp("local335 (season-min point scorer's constructors)", con.execute(q335).fetchall(), "local335_a.csv")
# local309 gold variant a: the official champions = final standings (drop scores, best-car rule), falling back
# to results sums for 1950-1957 constructors (no constructor standings then)
q309a = """with dfin as (select ra.year, d.driver_id, d.points from driver_standings d join races ra using(race_id)
             where ra.round = (select max(r2.round) from races r2 join driver_standings x using(race_id) where r2.year = ra.year)),
 cfin as (select ra.year, c.constructor_id, c.points from constructor_standings c join races ra using(race_id)
             where ra.round = (select max(r2.round) from races r2 join constructor_standings x using(race_id) where r2.year = ra.year)),
 cp as (select ra.year, r.constructor_id, sum(r.points) p from results r join races ra using(race_id) group by 1,2),
 bd as (select year, driver_id from dfin d where points = (select max(points) from dfin d2 where d2.year = d.year)),
 bc as (select year, constructor_id from cfin c where points = (select max(points) from cfin c2 where c2.year = c.year)
        union all select year, constructor_id from cp c where year not in (select year from cfin) and p = (select max(p) from cp c2 where c2.year = c.year))
select bd.year, dr.forename || ' ' || dr.surname, c.name from bd join bc using(year) join drivers dr using(driver_id) join constructors c using(constructor_id) order by 1, 2, 3"""
cmp("local309 (final standings champions; results sums before 1958)", con.execute(q309a).fetchall(), "local309_a.csv")
o = con.execute(open(os.path.join(G, "local309.sql")).read()).fetchall()
for f in ("local309_a.csv", "local309_b.csv", "local309_c.csv"):
    g = gold(f)
    same = sum(1 for x, y in zip(o, g) if [str(x[0]), x[1] or '', x[2] or ''] == y[:1] + y[1:2] + [y[-1] if f != "local309_b.csv" else y[3]])
    print(f"gold SQL output vs {f}: {len(o)} vs {len(g)} rows, {same} rows equal position-by-position")
a, g = norm(con.execute(q309).fetchall()), normg(gold("local309_a.csv"))
print("local309 results-sum rewrite vs local309_a.csv: years differing", [x[0] for x, y in zip(a, g) if x != y])
