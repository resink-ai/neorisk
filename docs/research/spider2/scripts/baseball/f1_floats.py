"""Float and mixed-column checks. Usage: python3 -I f1_floats.py DB
1) mixed columns: declared INTEGER/REAL/NUMERIC affinity holding any text value (per the contract they become string)
2) every REAL cell: SQLite CAST(x AS TEXT) vs Python shortest repr; and text round trip float(cast)==x
3) derived-column tests: era = round(27*er/ipouts, 2), baopp formulas, team.era, team.fp"""
import sqlite3, sys, math, decimal
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
mixed, real_cols, nulls = [], [], 0
for t in tabs:
    for _, c, decl, *_ in con.execute(f'pragma table_info("{t}")'):
        ty = dict(con.execute(f'select typeof("{c}"), count(*) from "{t}" group by 1'))
        nulls += ty.get('null', 0)
        if decl.upper() in ('INTEGER', 'REAL', 'NUMERIC') and 'text' in ty:
            nonempty = con.execute(f'select count(*) from "{t}" where typeof("{c}")=\'text\' and "{c}"<>\'\'').fetchone()[0]
            mixed.append((t, c, decl, ty.get('text'), nonempty))
        if 'real' in ty: real_cols.append((t, c))
print("NULL cells in the whole catalog:", nulls)
print(f"mixed columns (numeric affinity holding text): {len(mixed)}")
for m in mixed: print("  %s.%s %s text=%d non-empty text=%d" % m)
tot_num = sum(1 for t in tabs for r in con.execute(f'pragma table_info("{t}")') if r[2].upper() in ('INTEGER','REAL','NUMERIC'))
print("numeric-affinity columns in total:", tot_num)
print("\nREAL cells: CAST AS TEXT vs repr")
for t, c in real_cols:
    rows = con.execute(f'select "{c}", cast("{c}" as text) from "{t}" where typeof("{c}")=\'real\'').fetchall()
    diff = [(x, s) for x, s in rows if s != repr(x)]
    rt = sum(1 for x, s in rows if float(s) == x)
    dec = {}
    for x, _ in rows:
        d = -decimal.Decimal(repr(x)).as_tuple().exponent; dec[d] = dec.get(d, 0) + 1
    print(f"  {t}.{c}: real={len(rows)} cast!=repr={len(diff)} {diff[:3]} cast_roundtrips={rt} decimals={dict(sorted(dec.items()))}")

def test(name, sql):
    n, ok = 0, 0; bad = []
    for row in con.execute(sql):
        n += 1
        if row[-1]: ok += 1
        elif len(bad) < 5: bad.append(row[:-1])
    print(f"  {name}: rows={n} match={ok} examples_of_mismatch={bad}")
print("\nderived columns")
test("pitching.era = round(27*er/ipouts,2) where ipouts>0 and era<>''",
     "select player_id, year, er, ipouts, era, abs(era - round(27.0*er/ipouts,2)) < 1e-9 from pitching where ipouts<>'' and ipouts>0 and era<>''")
test("pitching.era within 0.005 of 27*er/ipouts",
     "select player_id, year, er, ipouts, era, abs(era - 27.0*er/ipouts) <= 0.0050001 from pitching where ipouts<>'' and ipouts>0 and era<>''")
test("pitching.era='' <-> ipouts=0 (rows with era='')",
     "select player_id, year, ipouts, er, ipouts=0 from pitching where era=''")
test("pitching.baopp = round(h/(bfp-bb-hbp-sh-sf),3) (all present)",
     "select player_id, year, h, bfp, baopp, abs(baopp - round(1.0*h/(bfp-bb-hbp-sh-sf),3))<1e-9 from pitching where baopp<>'' and bfp<>'' and hbp<>'' and sh<>'' and sf<>'' and (bfp-bb-hbp-sh-sf)>0")
test("pitching.baopp = round(h/(bfp-bb-hbp-sh-sf),2) (all present)",
     "select player_id, year, h, bfp, baopp, abs(baopp - round(1.0*h/(bfp-bb-hbp-sh-sf),2))<1e-9 from pitching where baopp<>'' and bfp<>'' and hbp<>'' and sh<>'' and sf<>'' and (bfp-bb-hbp-sh-sf)>0")
test("pitching.baopp = round(h/(ipouts+h),3)",
     "select player_id, year, h, ipouts, baopp, abs(baopp - round(1.0*h/(ipouts+h),3))<1e-9 from pitching where baopp<>'' and ipouts<>'' and ipouts+h>0")
test("pitching.baopp decimals<=2 (2-digit rounding)", "select player_id, baopp, abs(baopp*100 - round(baopp*100))<1e-6 from pitching where baopp<>''")
test("team.era = round(27*er/ipouts,2)",
     "select year, team_id, er, ipouts, era, abs(era - round(27.0*er/ipouts,2))<1e-9 from team")
test("team.fp decimals<=3", "select year, team_id, fp, abs(fp*1000-round(fp*1000))<1e-6 from team")
test("pitching_postseason.era = round(27*er/ipouts,2)",
     "select player_id, year, round, er, ipouts, era, abs(era - round(27.0*er/ipouts,2))<1e-9 from pitching_postseason where ipouts>0 and era<>'' and era<>'inf'")
test("pitching_postseason era '' or inf <-> ipouts=0",
     "select player_id, year, round, ipouts, er, era, ipouts=0 from pitching_postseason where era='' or era='inf'")
test("pitching_postseason ipouts=0 -> era in ('', 'inf')",
     "select player_id, year, round, er, era, era in ('','inf') from pitching_postseason where ipouts=0")
