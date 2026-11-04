"""Match's XML incident columns, the betting odds and Player.height: byte-exactness and
decomposability. Read-only.
Usage: python3 -I p2_match_text.py data/spider2/EU_soccer.sqlite"""
import sqlite3, sys, collections, math
import xml.etree.ElementTree as ET

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro&immutable=1", uri=True)
XCOLS = ["goal", "shoton", "shotoff", "foulcommit", "card", "cross", "corner", "possession"]
players = {r[0] for r in con.execute("select player_api_id from Player")}

print("## XML columns")
rows = con.execute(f"select id, league_id, season, home_team_api_id, away_team_api_id, home_team_goal, away_team_goal, "
                   f"{', '.join(chr(34)+c+chr(34) for c in XCOLS)} from Match").fetchall()
nonnull_pattern = collections.Counter()
for r in rows:
    nonnull_pattern[tuple(v is not None for v in r[7:])] += 1
print("null pattern across the 8 columns (True=present):", dict(nonnull_pattern))
by_league = collections.Counter((r[1], r[2]) for r in rows if r[7] is not None)
tot_league = collections.Counter((r[1], r[2]) for r in rows)
print("league,season with XML present / total:")
for k in sorted(tot_league):
    print("  ", k, by_league.get(k, 0), "/", tot_league[k])

for ci, c in enumerate(XCOLS):
    vals = [(r[0], r[7 + ci]) for r in rows if r[7 + ci] is not None]
    empty = sum(v == f"<{c} />" for _, v in vals)
    parse_fail = rt_equal = nonascii = ws = 0
    seqs = collections.Counter()
    nvalues = 0
    subtypes = collections.Counter()
    for mid, v in vals:
        if any(ord(ch) > 127 for ch in v): nonascii += 1
        if "\n" in v or "\r" in v or "\t" in v or v != v.strip(): ws += 1
        try:
            root = ET.fromstring(v)
        except ET.ParseError:
            parse_fail += 1; continue
        out = ET.tostring(root, encoding="unicode", short_empty_elements=True)
        if out == v: rt_equal += 1
        for val in root.findall("value"):
            nvalues += 1
            seqs[tuple(ch.tag for ch in val)] += 1
            st = val.find("subtype")
            subtypes[st.text if st is not None else None] += 1
    print(f"\n### {c}: present {len(vals)}, empty '<{c} />' {empty}, parse failures {parse_fail}, "
          f"ElementTree re-serialisation byte-equal {rt_equal}/{len(vals)}, non-ASCII {nonascii}, whitespace/newline {ws}")
    print(f"   <value> incidents {nvalues}; distinct child-tag orders {len(seqs)}; top 3:")
    for s, n in seqs.most_common(3):
        print("     ", n, ",".join(s))
    print("   top subtypes:", subtypes.most_common(8))

print("\n## goal XML vs score")
pp = [r[0] for r in rows if r[7] is not None and ("\n" in r[7] or r[7] != r[7].strip())]
print("matches whose XML has newlines/tabs (pretty-printed):", pp,
      [sum(("\n" in (r[7+i] or "")) for r in rows) for i in range(8)])
gtypes = collections.Counter()
for r in rows:
    if r[7] is None: continue
    for val in ET.fromstring(r[7]).findall("value"):
        gtypes[(val.findtext("goal_type"), val.findtext("comment"))] += 1
print("goal (goal_type, comment) counts:", gtypes.most_common())
agree = disagree = 0; samples = []
for r in rows:
    if r[7] is None: continue
    root = ET.fromstring(r[7])
    h = a = 0
    for val in root.findall("value"):
        t = val.findtext("team"); gt = val.findtext("goal_type") or val.findtext("comment")
        if t is None: continue
        t = int(t)
        if gt == "dg": continue          # disallowed goal
        own = gt == "o"
        if (t == r[3]) != own: h += 1
        else: a += 1
    if (h, a) == (r[5], r[6]): agree += 1
    else:
        disagree += 1
        if len(samples) < 5: samples.append((r[0], (r[5], r[6]), (h, a)))
print(f"goal XML incident count (own goals credited to the other side) equals the score: {agree}; differs: {disagree}; samples {samples}")

print("\n## XML player and team refs")
pref = orphan = team_other = 0; nonint = collections.Counter()
for r in rows:
    for v in r[7:]:
        if v is None: continue
        root = ET.fromstring(v)
        for val in root.findall("value"):
            for tag in ("player1", "player2"):
                x = val.findtext(tag)
                if x is not None:
                    pref += 1
                    if not x.isdigit(): nonint[x] += 1
                    elif int(x) not in players: orphan += 1
            t = val.findtext("team")
            if t is not None and int(t) not in (r[3], r[4]): team_other += 1
print(f"player refs {pref}, numeric but not in Player {orphan}, non-numeric {dict(nonint)}; team refs not the home/away team {team_other}")

print("\n## odds")
ocols = [c[1] for c in con.execute("pragma table_info(Match)") if c[2] == "NUMERIC"]
tot = notcent = cls_int = 0; dec = collections.Counter()
for c in ocols:
    for (v, t, txt) in con.execute(f'select "{c}", typeof("{c}"), cast("{c}" as text) from Match where "{c}" is not null'):
        tot += 1
        if t == "integer": cls_int += 1
        cents = round(v * 100)
        if cents / 100 != v: notcent += 1
        s = repr(float(v)); d = len(s.split(".")[1].rstrip("0")) if "." in s else 0
        dec[d] += 1
print(f"odds cells {tot} in {len(ocols)} columns; integer class {cls_int}; not exact hundredths (round(v*100)/100 != v) {notcent}")
print("decimal places of shortest repr:", sorted(dec.items()))
zero = con.execute("select " + " + ".join(f'sum("{c}"<=1)' for c in ocols) + " from Match").fetchone()[0]
print("odds <= 1.0:", zero)
# a bookmaker's three prices are present together?
for b in sorted({c[:-1] for c in ocols}):
    n = con.execute(f'select sum(({b}H is null)+({b}D is null)+({b}A is null) in (1,2)) from Match').fetchone()[0]
    print(f"  {b}: matches with only some of H/D/A null = {n}")
# overround
ov = con.execute("select min(1.0/B365H+1.0/B365D+1.0/B365A), avg(1.0/B365H+1.0/B365D+1.0/B365A), max(1.0/B365H+1.0/B365D+1.0/B365A) from Match where B365H is not null").fetchone()
print("B365 overround min/avg/max:", ov)

print("\n## Player.height = inches * 2.54 ?")
ok = bad = 0
for (h,) in con.execute("select height from Player"):
    inch = round(h / 2.54)
    if inch * 2.54 == h: ok += 1
    else: bad += 1
print(f"height == round(height/2.54)*2.54 in double: {ok}; differs {bad}")
ok2 = sum(1 for (h,) in con.execute("select height from Player") if float(repr(h)) == h and round(h*100)/100 == h)
print(f"height exact hundredths: {ok2}")
