"""Probe: rebuild lap_positions = race laps + lap-0 start rows + retirement rows; multiset diff.
Usage: python3 -I p5_lap_positions_probe.py data/spider2/f1.sqlite"""
import sqlite3, sys, collections
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
src = collections.Counter(con.execute("select race_id, driver_id, lap, position, lap_type from lap_positions"))
parts = {
"race": "select race_id, driver_id, lap, position, 'Race' from lap_times",
"start": """select r.race_id, r.driver_id, 0,
   case when r.grid = 0 then (select count(*) from results r2 where r2.race_id = r.race_id) else r.grid end,
   case when q.position is null then 'Starting Position - No Qualification'
        when r.grid = 0 then 'Starting Position - Pit Lane Start'
        when r.grid > q.position then 'Starting Position - Grid Drop'
        when r.grid < q.position then 'Starting Position - Grid Increase'
        else 'Starting Position - Qualifying' end
   from results r left join qualifying q on q.race_id = r.race_id and q.driver_id = r.driver_id""",
"retire": "select race_id, driver_id, lap, position_order, retirement_type from retirements",
}
cand = collections.Counter()
for name, sql in parts.items():
    rows = con.execute(sql).fetchall(); cand.update(rows); print(name, len(rows))
miss, extra = src - cand, cand - src
print("src", sum(src.values()), "cand", sum(cand.values()), "src-not-cand", sum(miss.values()), "cand-not-src", sum(extra.values()))
print("by type missing", collections.Counter(k[4] for k in miss.elements()))
print("by type extra  ", collections.Counter(k[4] for k in extra.elements()))
for k in list(miss)[:10]: print("  miss", k)
for k in list(extra)[:10]: print("  extra", k)
