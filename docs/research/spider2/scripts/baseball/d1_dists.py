"""Distributions for stage 2. Usage: python3 -I d1_dists.py DB"""
import sqlite3, sys, statistics as st
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = lambda s: con.execute(s).fetchall()
def qs(vals, ps=(5,25,50,75,90,99)):
    v = sorted(vals); n = len(v)
    return {p: v[min(n-1, int(p/100*n))] for p in ps} | {"max": v[-1], "n": n, "mean": round(sum(v)/n, 2)}
print("debuts per decade:", q("select substr(debut,1,3)||'0s', count(*) from player where debut<>'' group by 1"))
print("teams per year (selected):", q("select year, count(*) from team where year in (1871,1876,1900,1901,1914,1950,1961,1969,1977,1993,1998,2015) group by 1"))
print("batting rows per year (selected):", q("select year, count(*) from batting where year in (1871,1900,1950,1980,2000,2015) group by 1"))
print("stints per player-year:", q("select n, count(*) from (select player_id, year, max(stint) n from batting group by 1,2) group by 1"))
car = [r[0] for r in q("select count(distinct year) from batting group by player_id")]
print("seasons per player (batting):", qs(car))
print("seasons per player histogram 1,2,3-5,6-10,11-15,16+:",
      [sum(1 for c in car if c==1), sum(1 for c in car if c==2), sum(1 for c in car if 3<=c<=5), sum(1 for c in car if 6<=c<=10), sum(1 for c in car if 11<=c<=15), sum(1 for c in car if c>=16)])
span_days = [r[0] for r in q("select cast(julianday(final_game)-julianday(debut) as int) from player where debut<>''")]
print("career span days (final_game - debut):", qs(span_days), "zero-day careers:", sum(1 for d in span_days if d==0))
print("batting AB per row (non-empty):", qs([r[0] for r in q("select ab from batting where ab<>''")]))
print("batting HR per row (non-empty):", qs([r[0] for r in q("select hr from batting where hr<>''")]))
print("rows with ab=0:", q("select count(*) from batting where ab=0"))
print("fielding pos mix:", q("select pos, count(*) from fielding group by 1 order by 2 desc"))
for y in (1985, 1995, 2005, 2015):
    print(f"salary {y}:", qs([r[0] for r in q(f'select salary from salary where year={y}')]))
print("salary rows per year (selected):", q("select year, count(*) from salary where year in (1985,1990,2000,2010,2015) group by 1"))
print("debut month mix:", q("select substr(debut,6,2), count(*) from player where debut<>'' group by 1"))
print("debut weekday mix (0=Sun):", q("select strftime('%w',debut), count(*) from player where debut<>'' group by 1"))
print("bats mix:", q("select bats, count(*) from player group by 1"), "throws mix:", q("select throws, count(*) from player group by 1"))
print("birth_country top:", q("select birth_country, count(*) from player group by 1 order by 2 desc limit 6"))
print("height (in):", qs([r[0] for r in q("select height from player where height<>''")]), "weight (lb):", qs([r[0] for r in q("select weight from player where weight<>''")]))
print("all-star rows per year (selected):", q("select year, count(*) from all_star where year in (1933,1960,1990,2015) group by 1"))
print("hof: rows per yearid top:", q("select yearid, count(*) from hall_of_fame group by 1 order by 2 desc limit 5"), "inducted share:", q("select inducted, count(*) from hall_of_fame group by 1"))
print("hof: ballots per player:", q("select n, count(*) from (select player_id, count(*) n from hall_of_fame group by 1) group by 1 order by 1 limit 20"))
print("pitching ERA (non-empty, ipouts>=150):", qs([r[0] for r in q("select era from pitching where era<>'' and ipouts>=150")]))
print("team win pct:", qs([r[0] for r in q("select round(1.0*w/(w+l),3) from team where w+l>0")]))
print("managers per team-season:", q("select n, count(*) from (select year, team_id, count(*) n from manager group by 1,2) group by 1"))
print("home_game parks per team-season:", q("select n, count(*) from (select year, team_id, count(*) n from home_game group by 1,2) group by 1"))
print("postseason rounds per year (selected):", q("select year, count(*) from postseason where year in (1903,1969,1995,2012,2015) group by 1"))
print("colleges per player:", q("select n, count(*) from (select player_id, count(distinct college_id) n from player_college group by 1) group by 1"))
print("college years per player:", q("select n, count(*) from (select player_id, count(*) n from player_college group by 1) group by 1"))
print("season end (max span_last in home_game) selected years:", q("select year, max(span_last), min(span_first) from home_game where year in (1871,1900,1950,2000,2014) group by 1"))
print("all-star game date range (mmdd):", q("select min(substr(game_id,8,4)), max(substr(game_id,8,4)) from all_star where game_id<>''"))
