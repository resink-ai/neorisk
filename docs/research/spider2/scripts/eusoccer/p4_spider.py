"""Reproduce Spider2 gold answers for the EU_soccer questions and compare with the gold CSVs in
gold/. Also runs the one gold SQL (local219) as published. Read-only.
Usage: python3 -I p4_spider.py data/spider2/EU_soccer.sqlite"""
import csv, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro&immutable=1", uri=True)
gold = lambda f: list(csv.reader(open(os.path.join(HERE, "gold", f), encoding="utf-8")))

SIDES = " union all ".join(
    f"select id mid, home_team_api_id team, {s}_player_{i} pid, "
    f"case when home_team_goal>away_team_goal then 'W' when home_team_goal<away_team_goal then 'L' else 'D' end r from Match"
    .replace("home_team_api_id team", "home_team_api_id team" if s == "home" else "away_team_api_id team")
    .replace("then 'W' when home_team_goal<away_team_goal then 'L'",
             "then 'W' when home_team_goal<away_team_goal then 'L'" if s == "home"
             else "then 'L' when home_team_goal<away_team_goal then 'W'")
    for s in ("home", "away") for i in range(1, 12))

TEAM_RES = """
with r as (
 select season, league_id, home_team_api_id team, home_team_goal gf, away_team_goal ga from Match
 union all select season, league_id, away_team_api_id, away_team_goal, home_team_goal from Match)"""

def run(name, sql):
    rows = con.execute(sql).fetchall()
    print(f"### {name} ({len(rows)} rows)")
    for r in rows[:15]: print("  ", r)
    return rows

# local218: median over teams of each team's best season goal total
r = run("local218 median of max season goals", TEAM_RES + """,
 s as (select team, season, sum(gf) g from r group by 1,2),
 m as (select team, max(g) g from s group by 1),
 o as (select g, row_number() over (order by g) rn, count(*) over () n from m)
 select avg(g) median, max(n) teams from o where rn in ((n+1)/2, (n+2)/2)""")
print("   gold:", gold("local218_a.csv")[1], "match:", float(gold("local218_a.csv")[1][0]) == r[0][0])

# local221: top 10 teams by total wins
r = run("local221 top10 wins", TEAM_RES + """
 select t.team_long_name, sum(gf>ga) w from r join Team t on t.team_api_id=r.team group by r.team order by w desc limit 10""")
g = [(a, int(b)) for a, b in gold("local221_a.csv")[1:]]
print("   match gold:", [tuple(x) for x in r] == g)

# local283: champion per league-season, 3/1/0 points
r = run("local283 champions", TEAM_RES + """,
 p as (select season, league_id, team, sum(case when gf>ga then 3 when gf=ga then 1 else 0 end) pts from r group by 1,2,3),
 k as (select p.*, rank() over (partition by season, league_id order by pts desc) rk from p)
 select k.season, t.team_long_name, l.name, c.name, k.pts from k join Team t on t.team_api_id=k.team
 join League l on l.id=k.league_id join Country c on c.id=l.country_id where rk=1 order by 1, 3""")
g = [(a, b, c, d, int(e)) for a, b, c, d, e in gold("local283_a.csv")[1:]]
print("   rows", len(r), "gold rows", len(g), "multiset equal:", sorted(map(tuple, r)) == sorted(g),
      "| every gold row is a champion here:", set(g) <= set(map(tuple, r)),
      "| extra rows (ties gold broke):", sorted(set(map(tuple, r)) - set(g)))
ties = con.execute(TEAM_RES + """,
 p as (select season, league_id, team, sum(case when gf>ga then 3 when gf=ga then 1 else 0 end) pts from r group by 1,2,3),
 k as (select p.*, rank() over (partition by season, league_id order by pts desc) rk from p)
 select count(*) from (select season, league_id from k where rk=1 group by 1,2 having count(*)>1)""").fetchone()[0]
print("   league-seasons with a tie for first:", ties)

# local220: players in the most won / lost matches (distinct matches, NULL slots excluded)
r = run("local220 most wins / most losses", f"""
 with s as (select distinct mid, pid, r from ({SIDES}) where pid is not null),
 c as (select pid, sum(r='W') w, sum(r='L') l from s group by 1)
 select 'most_wins', p.player_name, w, l from c join Player p on p.player_api_id=c.pid where w=(select max(w) from c)
 union all select 'most_losses', p.player_name, w, l from c join Player p on p.player_api_id=c.pid where l=(select max(l) from c)""")
print("   gold a:", gold("local220_a.csv")[1:], " b:", gold("local220_b.csv")[1:])

# local219: gold SQL as published (it inlines match_view); compare with the 3 accepted CSVs
sql219 = open(os.path.join(HERE, "gold", "local219.sql"), encoding="utf-8").read()
r = run("local219 gold SQL", sql219)
for f in ("local219_a.csv", "local219_b.csv", "local219_c.csv"):
    g = [tuple(x[:2]) for x in gold(f)[1:]]
    print(f"   equals {f} on (league, team): {[tuple(x) for x in r] == g}")
r = run("local219 fewest wins per league, all tied teams", TEAM_RES + """,
 w as (select league_id, team, sum(gf>ga) w from r group by 1,2),
 k as (select w.*, rank() over (partition by league_id order by w) rk from w)
 select l.name, group_concat(t.team_long_name, ' | '), min(w) from k join Team t on t.team_api_id=k.team join League l on l.id=k.league_id
 where rk=1 group by l.name order by 1""")
r = run("match_view row count = Match row count", "select (select count(*) from match_view), (select count(*) from Match)")
