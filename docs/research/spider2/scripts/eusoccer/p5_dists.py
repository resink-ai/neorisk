"""Distributions to fit for stage 2, plus sizes and the entity-creation rule check. Read-only.
Usage: python3 -I p5_dists.py data/spider2/EU_soccer.sqlite"""
import sqlite3, sys, statistics as st

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro&immutable=1", uri=True)
q = lambda s: con.execute(s).fetchall()

def quant(vals, ps=(0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99)):
    v = sorted(vals); n = len(v)
    return {p: v[min(n - 1, int(p * n))] for p in ps}

print("## per league: matches, home/draw/away %, goals per match (home, away)")
for r in q("""select l.name, count(*), round(100.0*avg(home_team_goal>away_team_goal),1), round(100.0*avg(home_team_goal=away_team_goal),1),
  round(100.0*avg(home_team_goal<away_team_goal),1), round(avg(home_team_goal),3), round(avg(away_team_goal),3)
  from Match m join League l on l.id=m.league_id group by 1 order by 1"""):
    print("  ", r)

print("\n## goals: is a Poisson fit plausible? mean and variance per side")
for side in ("home_team_goal", "away_team_goal"):
    v = [r[0] for r in q(f"select {side} from Match")]
    print(f"   {side}: mean {st.mean(v):.4f} var {st.pvariance(v):.4f}")
print("   P(0-0):", q("select round(avg(home_team_goal=0 and away_team_goal=0),4) from Match")[0][0])

print("\n## B365 favourite: implied probability vs outcome")
for r in q("""with b as (select case when B365H<=B365D and B365H<=B365A then 'H' when B365A<=B365D then 'A' else 'D' end fav,
  case when home_team_goal>away_team_goal then 'H' when home_team_goal<away_team_goal then 'A' else 'D' end res,
  (1.0/B365H)/(1.0/B365H+1.0/B365D+1.0/B365A) ph from Match where B365H is not null)
  select fav, count(*), round(avg(fav=res),4) from b group by 1"""):
    print("  ", r)
print("   bookmaker coverage (matches with a quote):",
      q("select " + ",".join(f"sum({b}H is not null)" for b in ["B365","BW","IW","LB","PS","WH","SJ","VC","GB","BS"]) + " from Match")[0])
print("   bookmaker quote triplets in total:",
      q("select " + "+".join(f"sum({b}H is not null)" for b in ["B365","BW","IW","LB","PS","WH","SJ","VC","GB","BS"]) + " from Match")[0][0])
print("   matches with no odds at all:", q("select count(*) from Match where " + " and ".join(f"{b}H is null" for b in ["B365","BW","IW","LB","PS","WH","SJ","VC","GB","BS"]))[0][0])

print("\n## player ratings")
v = [r[0] for r in q("select overall_rating from Player_Attributes where overall_rating is not null")]
print("   overall_rating quantiles:", quant(v), "mean", round(st.mean(v), 2))
v = [r[0] for r in q("select potential-overall_rating from Player_Attributes where overall_rating is not null")]
print("   potential - rating quantiles:", quant(v))
v = [r[0] for r in q("""select r1-r0 from (select overall_rating r1, lag(overall_rating) over (partition by player_api_id order by date, id) r0
   from Player_Attributes where overall_rating is not null) where r0 is not null""")]
print("   rating change between consecutive snapshots: quantiles", quant(v), "share 0:", round(sum(x == 0 for x in v) / len(v), 4))
v = [r[0] for r in q("select count(*) from Player_Attributes group by player_api_id")]
print("   snapshots per player: quantiles", quant(v), "mean", round(st.mean(v), 2))
print("   preferred foot right share:", q("select round(avg(preferred_foot='right'),4) from Player_Attributes where preferred_foot is not null")[0][0])

print("\n## players")
print("   birth year quantiles:", quant([int(r[0]) for r in q("select substr(birthday,1,4) from Player")]))
print("   height cm quantiles:", quant([r[0] for r in q("select height from Player")]))
print("   weight lb quantiles:", quant([r[0] for r in q("select weight from Player")]))
lineup = " union all ".join(f"select {s}_player_{i} p from Match" for s in ("home", "away") for i in range(1, 12))
v = [r[0] for r in q(f"select count(*) from ({lineup}) where p is not null group by p")]
print("   lineup appearances per player: quantiles", quant(v), "max", max(v))

print("\n## teams")
v = [r[0] for r in q("select count(distinct season) from (select home_team_api_id t, season from Match) group by t")]
print("   seasons per team:", {k: v.count(k) for k in sorted(set(v))})

print("\n## sizes")
x = q("select sum(length(goal)+length(shoton)+length(shotoff)+length(foulcommit)+length(card)+length(\"cross\")+length(corner)+length(possession)) from Match")[0][0]
print("   XML characters in Match (8 columns):", x)

print("\n## creation rule check")
print("   players: first PA date <= first lineup date for all? see q3:player_first_seen")
r = q(f"""with fm as (select t.team_api_id t, (select min(date) from Match m where m.home_team_api_id=t.team_api_id or m.away_team_api_id=t.team_api_id) fm,
   (select min(date) from Team_Attributes a where a.team_api_id=t.team_api_id) fa from Team t)
   select count(*), sum(fa is not null and fa < fm), min(min(fm, ifnull(fa, fm))), max(min(fm, ifnull(fa, fm))) from fm""")
print("   teams: n, created by first TA (before first match), min/max created_at:", r[0])
r = q("select l.id, min(m.date) from League l join Match m on m.league_id=l.id group by 1 order by 2")
print("   leagues' first match:", r)
