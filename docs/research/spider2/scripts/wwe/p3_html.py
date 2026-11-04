"""Are Cards' and Matches' structured columns a parse of the stored HTML?
1. Tables.html (listing page): each row = date, promotion, card link + name, city, state.
   Check each card's own row in its listing page against Cards.event_date / Events.name / Locations.name.
2. Cards.info_html: Date link, Promotion text, venue city/state.
3. Cards.match_html: one <tr> per match: no., side A, result, side B, duration, match type, title(s).
   Check against the card's distinct matches (the first copy, p2).
Usage: python3 -I p3_html.py DB"""
import re, sqlite3, sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from html import unescape


class Rows(HTMLParser):
    """Collect table rows: each row is a list of cells; each cell = (text, [(href, anchor text)])."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.a = [], None, None, None
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        elif tag in ("td", "th") and self.row is not None: self.cell = [[], []]
        elif tag == "a" and self.cell is not None: self.a = [dict(attrs).get("href"), []]
    def handle_endtag(self, tag):
        if tag == "a" and self.a is not None and self.cell is not None:
            self.cell[1].append((self.a[0], " ".join(" ".join(self.a[1]).split()))); self.a = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append((" ".join(" ".join(self.cell[0]).split()), self.cell[1])); self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row); self.row = None
    def handle_data(self, d):
        if self.cell is not None: self.cell[0].append(d)
        if self.a is not None: self.a[1].append(d)


def parse(h):
    p = Rows(); p.feed(h); p.close(); return p.rows


con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
promo = dict(con.execute("SELECT id, name FROM Promotions"))
loc = dict(con.execute("SELECT id, name FROM Locations"))
evn = dict(con.execute("SELECT id, name FROM Events"))
wr = dict(con.execute("SELECT id, name FROM Wrestlers"))
belt = dict(con.execute("SELECT id, name FROM Belts"))
mt = dict(con.execute("SELECT id, name FROM Match_Types"))
cards = con.execute("SELECT id, table_id, location_id, promotion_id, event_date, event_id, url, info_html, match_html FROM Cards").fetchall()
tables = dict(con.execute("SELECT id, html FROM Tables"))
BASE = "http://www.profightdb.com"

# 1. listing pages
listing = {}  # url -> (table_id, date_href, promo, name, location)
rows_per_table = Counter()
for tid, h in tables.items():
    for r in parse(h):
        if len(r) < 4 or not r[2][1]: continue
        href, name = r[2][1][0]
        dl = r[0][1][0][0] if r[0][1] else None
        locs = [t for _, t in r[3][1]]
        listing.setdefault(BASE + href, []).append((tid, dl, r[1][0], name, ", ".join(locs)))
        rows_per_table[tid] += 1
print("listing rows per table:", sorted(Counter(rows_per_table.values()).items()))
print("distinct card urls in listings:", len(listing), "; listed more than once:", sum(len(v) > 1 for v in listing.values()))
ok = Counter()
for (cid, tid, lid, pid, d, eid, url, info, mh) in cards:
    L = listing.get(url)
    ok["card_in_some_listing"] += L is not None
    if not L: continue
    own = [x for x in L if x[0] == tid]
    ok["card_in_own_table"] += bool(own)
    x = (own or L)[0]
    mm, dd, yy = re.search(r"(\d\d)-(\d\d)-(\d{4})", x[1]).groups()
    ok["date_eq"] += f"{yy}-{mm}-{dd}" == d
    ok["promo_eq"] += x[2] == promo[pid]
    ok["event_name_eq"] += unescape(x[3]) == evn[eid]
    ok["location_eq"] += x[4] == loc[lid]
print("listing checks over", len(cards), "cards:", dict(ok))
miss = [(c[0], c[6]) for c in cards if c[6] not in listing][:5]
print("cards missing from every listing (first 5):", miss)

# 2. info_html
ok = Counter(); bad = defaultdict(list)
for (cid, tid, lid, pid, d, eid, url, info, mh) in cards:
    m = re.search(r"this-day-in-history/(\d\d)-(\d\d)-(\d{4})", info)
    if m and f"{m.group(3)}-{m.group(1)}-{m.group(2)}" == d: ok["date"] += 1
    else: bad["date"].append(cid)
    t = re.search(r"Promotion:\s*</strong>\s*([^<]*?)\s*</td>", info)
    if t and t.group(1) == promo[pid]: ok["promotion"] += 1
    else: bad["promotion"].append((cid, t.group(1) if t else None, promo[pid]))
    rs = parse(info)
    venue_cells = [c for r in rs for c in r if c[0].startswith("Venue:")]
    if venue_cells:
        anchors = [t for _, t in venue_cells[0][1]]
        if ", ".join(anchors[-2:]) == loc[lid]: ok["location_last2"] += 1
        else: bad["location_last2"].append((cid, anchors, loc[lid]))
print("info_html checks:", dict(ok))
for k, v in bad.items(): print("  info_html mismatches", k, len(v), v[:4])

# 3. match_html vs distinct matches (first block per card)
first, done, prev = defaultdict(list), set(), None
for r in con.execute("SELECT id, card_id, winner_id, win_type, loser_id, match_type_id, duration, title_id, title_change FROM Matches ORDER BY id"):
    if r[1] != prev:
        if prev is not None: done.add(prev)
        prev = r[1]
    if r[1] not in done: first[r[1]].append(r)
ok = Counter(); bad = defaultdict(list)
for (cid, tid, lid, pid, d, eid, url, info, mh) in cards:
    ms = first.get(cid, [])
    trs = [r for r in parse(mh) if r and r[0][0] != "no."]
    if len(trs) == len(ms): ok["row_count"] += 1
    else: bad["row_count"].append((cid, len(trs), len(ms))); continue
    for tr, m in zip(trs, ms):
        # the scraper's rule (found here): split every anchor text on ",", strip, sort, join with " & "
        side = lambda c: " & ".join(sorted(x.strip() for _, t in c[1] for x in t.split(",")))
        sideA = side(tr[1]) if len(tr) > 1 else None
        sideB = side(tr[3]) if len(tr) > 3 else None
        k = "winner_name"; (ok.__setitem__(k, ok[k] + 1) if sideA == wr[int(m[2])] else bad[k].append((cid, sideA, wr[int(m[2])])))
        k = "loser_name"; (ok.__setitem__(k, ok[k] + 1) if sideB == wr[int(m[4])] else bad[k].append((cid, sideB, wr[int(m[4])])))
        k = "win_type"; (ok.__setitem__(k, ok[k] + 1) if tr[2][0] == m[3] else bad[k].append((cid, tr[2][0], m[3])))
        k = "duration"; (ok.__setitem__(k, ok[k] + 1) if tr[4][0] == m[6] else bad[k].append((cid, tr[4][0], m[6])))
        mtt = tr[5][0].replace("\xa0", "").strip()
        k = "match_type"; (ok.__setitem__(k, ok[k] + 1) if mtt == mt[int(m[5])] else bad[k].append((cid, mtt, mt[int(m[5])])))
        bt = re.sub(r"\s*\(title change\)\s*", " ", tr[6][0]).strip() if len(tr) > 6 else ""
        k = "title"; (ok.__setitem__(k, ok[k] + 1) if bt == belt[int(m[7])] else bad[k].append((cid, tr[6][0], bt, belt[int(m[7])])))
        tc = int("title change" in tr[6][0].lower()) if len(tr) > 6 else 0
        k = "title_change"; (ok.__setitem__(k, ok[k] + 1) if tc == m[8] else bad[k].append((cid, tr[6][0], m[8])))
print("match_html checks (cards for row_count, matches for the rest):", dict(ok))
for k, v in bad.items(): print("  match_html mismatches", k, len(v), v[:4])

# 4. The card counter: number the listing data rows (pages in Tables id order, rows in page order).
#    Is Tables.id the number of its first row, and Cards.id the number of its listing row?
k, first_row, idx = 0, {}, {}
for tid in sorted(tables):
    for r in parse(tables[tid]):
        if len(r) < 4 or not r[2][1] or r[0][0] == "date": continue
        k += 1
        first_row.setdefault(tid, k)
        idx.setdefault(BASE + r[2][1][0][0], k)
print("listing data rows:", k, "; tables whose id = number of their first row:", sum(first_row[t] == t for t in tables), "of", len(tables))
print("cards whose id = number of their listing row:", sum(idx.get(c[6]) == c[0] for c in cards), "of", sum(c[6] in idx for c in cards), "listed cards")
cardurls = {c[6] for c in cards}
lost = sorted(v for u, v in idx.items() if u not in cardurls)
print("listing rows with no card:", len(lost), "first:", lost[:12])
lookup_ids = {"Locations": set(loc), "Events": set(evn), "Promotions": set(promo)}
cardids = {c[0] for c in cards}
for name, ids in lookup_ids.items():
    orphan = sorted(i for i in ids if i not in cardids)
    print(name, "ids that are not a card id:", len(orphan), "; of those, a listing row with no card:", sum(i in set(lost) for i in orphan),
          "; beyond the listing:", [i for i in orphan if i > k])
# event-name mismatches between the listing and Events
for (cid, tid, lid, pid, d, eid, url, info, mh) in cards:
    L = listing.get(url)
    if L and unescape(L[0][3]) != evn[eid]: print("  event name differs: card", cid, repr(L[0][3]), repr(evn[eid]))
