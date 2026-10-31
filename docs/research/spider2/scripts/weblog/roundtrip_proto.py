"""Prototype of the proposed event catalog: source tables -> events/entities -> tables, compared as multisets.
Times are held as datetime objects (as simkit would hold UTC µs) and formatted back with strftime.
Usage: python3 -I roundtrip_proto.py DB"""
import sqlite3, sys
from collections import Counter
from datetime import datetime

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
F = "%Y-%m-%d %H:%M:%S"
def t(v):
    try: return datetime.strptime(v, F)
    except (TypeError, ValueError): return None
def d(v): return datetime.strptime(v, "%Y-%m-%d")
def rows(sql): return con.execute(sql).fetchall()
RULE_T0 = datetime(2016, 1, 1)           # created_at of untimed entities: first day of the catalog
N = max(t(r[0]) for r in rows("select stamp from purchase_log"))   # snapshot: last stamp in the file

ev = {}       # event type -> list of dicts (event_time + attributes)
ent = {}      # entity table -> list of dicts
# --- logs that stay logs (src_rowid kept as ord) ---
ev["access_logged"] = []
for rid, s, u, a, st in rows("select rowid, session, user_id, action, stamp from access_log"):
    shifted = t(st) is None
    ev["access_logged"].append(dict(event_time=t(s) if shifted else t(st), shifted=shifted,
        session=None if shifted else s, user_id=u, action=a, path_in_stamp=st if shifted else None, src_rowid=rid))
ev["action_logged"] = [dict(event_time=t(st), session=s, user_id=u, action=a, category=c, products=p,
        amount=None if m is None else m * 100, src_rowid=rid)
    for rid, s, u, a, c, p, m, st in rows("select rowid, * from action_log")]
ev["action_with_ip_logged"] = [dict(event_time=t(st), session=s, user_id=u, action=a, ip=ip, src_rowid=rid)
    for rid, s, u, a, ip, st in rows("select rowid, * from action_log_with_ip")]
ev["noisy_action_logged"] = [dict(event_time=t(r[0]), row=r) for r in rows("select * from action_log_with_noise")]
ev["dup_action_logged"] = [dict(event_time=t(st), session=s, user_id=u, action=a, products=p, src_rowid=rid)
    for rid, st, s, u, a, p in rows("select rowid, * from dup_action_log")]
ev["invalid_action_logged"] = []
last = {}
for rid, st, s, u, a, c, p, m in rows("select rowid, * from invalid_action_log order by rowid"):
    tt = t(st)
    if tt is not None: last[s] = max(last.get(s, tt), tt)
    ev["invalid_action_logged"].append(dict(event_time=tt if tt else last[s], stamp_null=st is None, session=s,
        user_id=u, action=a, category=c, products=p, amount=None if m is None else m * 100, src_rowid=rid))
ev["activity_logged"] = [dict(event_time=t(st), session=s, action=a, option=o, path=p, search_type=q, src_rowid=rid)
    for rid, st, s, a, o, p, q in rows("select rowid, * from activity_log")]
ev["read_logged"] = [dict(event_time=t(st), session=s, action=a, url=u, src_rowid=rid)
    for rid, st, s, a, u in rows("select rowid, * from read_log")]
ev["form_viewed"] = [dict(event_time=t(st), session=s, action=a, path=p, status=x, src_rowid=rid)
    for rid, st, s, a, p, x in rows("select rowid, * from form_log")]
ev["form_error_logged"] = [dict(event_time=t(st), session=s, form=f, field=fl, error_type=e, value=v, src_rowid=rid)
    for rid, st, s, f, fl, e, v in rows("select rowid, * from form_error_log")]
ev["purchase_logged"] = [dict(event_time=t(st), purchase_id=i, user_id=u, amount=m * 100)
    for i, u, m, st in rows("select * from purchase_log")]
# --- masters as change logs ---
ev["user_registered"] = [dict(event_time=d(rd), user_id=u, sex=sx, birth_date=b, register_device=dv,
        withdraw_date=w, src_rowid=rid) for rid, u, sx, b, rd, dv, w in rows("select rowid, * from mst_users")]
ev["category_named"] = [dict(event_time=t(st), id=i, name=n) for i, n, st in rows("select * from mst_categories")]
old = {r[0]: r for r in rows("select * from mst_products_20161201")}
new = {r[0]: r for r in rows("select * from mst_products_20170101")}
ev["product_updated"] = [dict(event_time=t(r[3]), product_id=r[0], name=r[1], price=r[2] * 100) for r in old.values()]
ev["product_updated"] += [dict(event_time=t(r[3]), product_id=r[0], name=r[1], price=r[2] * 100)
                          for k, r in new.items() if old.get(k) != r]
ev["product_deleted"] = [dict(event_time=datetime(2016, 12, 1), product_id=k) for k in old if k not in new]
# --- untimed lookups as entities ---
ent["app1_users"] = [dict(ext_id=u, name=n, email=e, created_at=RULE_T0) for u, n, e in rows("select * from app1_mst_users")]
ent["app2_users"] = [dict(ext_id=u, name=n, phone=p, created_at=RULE_T0) for u, n, p in rows("select * from app2_mst_users")]
ent["user_cards"] = [dict(ext_id=u, card_number=c, created_at=RULE_T0) for u, c in rows("select * from mst_users_with_card_number")]
ent["product_sales"] = [dict(ext_id=p, category_name=c, sales=s, created_at=RULE_T0) for c, p, s in rows("select * from product_sales")]

# ---------------- rebuild ----------------
fmt = lambda x: x.strftime(F)
cents = lambda m: None if m is None else m // 100
R = {}
R["access_log"] = [(fmt(e["event_time"]) if e["shifted"] else e["session"], e["user_id"], e["action"],
                    e["path_in_stamp"] if e["shifted"] else fmt(e["event_time"])) for e in ev["access_logged"]]
R["action_log"] = [(e["session"], e["user_id"], e["action"], e["category"], e["products"], cents(e["amount"]), fmt(e["event_time"])) for e in ev["action_logged"]]
R["action_log_with_ip"] = [(e["session"], e["user_id"], e["action"], e["ip"], fmt(e["event_time"])) for e in ev["action_with_ip_logged"]]
R["action_log_with_noise"] = [e["row"] for e in ev["noisy_action_logged"]]
R["dup_action_log"] = [(fmt(e["event_time"]), e["session"], e["user_id"], e["action"], e["products"]) for e in ev["dup_action_logged"]]
R["invalid_action_log"] = [(None if e["stamp_null"] else fmt(e["event_time"]), e["session"], e["user_id"], e["action"], e["category"], e["products"], cents(e["amount"])) for e in ev["invalid_action_logged"]]
R["activity_log"] = [(fmt(e["event_time"]), e["session"], e["action"], e["option"], e["path"], e["search_type"]) for e in ev["activity_logged"]]
R["read_log"] = [(fmt(e["event_time"]), e["session"], e["action"], e["url"]) for e in ev["read_logged"]]
R["form_log"] = [(fmt(e["event_time"]), e["session"], e["action"], e["path"], e["status"]) for e in ev["form_viewed"]]
R["form_error_log"] = [(fmt(e["event_time"]), e["session"], e["form"], e["field"], e["error_type"], e["value"]) for e in ev["form_error_logged"]]
R["purchase_log"] = [(e["purchase_id"], e["user_id"], cents(e["amount"]), fmt(e["event_time"])) for e in ev["purchase_logged"]]
R["mst_users"] = [(e["user_id"], e["sex"], e["birth_date"], e["event_time"].strftime("%Y-%m-%d"), e["register_device"], e["withdraw_date"]) for e in ev["user_registered"]]
R["mst_categories"] = [(e["id"], e["name"], fmt(e["event_time"])) for e in ev["category_named"]]
def snapshot(cut):
    cur = {}
    for e in sorted(ev["product_updated"] + ev["product_deleted"], key=lambda e: e["event_time"]):
        if e["event_time"] >= cut: continue
        if "name" in e: cur[e["product_id"]] = (e["product_id"], e["name"], cents(e["price"]), fmt(e["event_time"]))
        else: cur.pop(e["product_id"], None)
    return list(cur.values())
R["mst_products_20161201"] = snapshot(datetime(2016, 12, 1))
R["mst_products_20170101"] = snapshot(datetime(2017, 1, 1))
R["app1_mst_users"] = [(e["ext_id"], e["name"], e["email"]) for e in ent["app1_users"]]
R["app2_mst_users"] = [(e["ext_id"], e["name"], e["phone"]) for e in ent["app2_users"]]
R["mst_users_with_card_number"] = [(e["ext_id"], e["card_number"]) for e in ent["user_cards"]]
R["product_sales"] = [(e["category_name"], e["ext_id"], e["sales"]) for e in ent["product_sales"]]

def key(v):            # type-aware: NULL, int/real by value, text exact
    return ("null",) if v is None else ("num", float(v)) if isinstance(v, (int, float)) else ("text", v)
ok = True
for tb in sorted(R):
    src = Counter(tuple(map(key, r)) for r in rows(f"select * from {tb}"))
    reb = Counter(tuple(map(key, r)) for r in R[tb])
    same = src == reb; ok &= same
    print(f"{tb:28s} source {sum(src.values()):4d}  rebuilt {sum(reb.values()):4d}  equal {same}")
print("ALL EQUAL", ok)
print()
for k in sorted(ev): print(f"event  {k:24s} {len(ev[k]):4d}")
for k in sorted(ent): print(f"entity {k:24s} {len(ent[k]):4d}")
print("events", sum(map(len, ev.values())), "in", len(ev), "types; entity rows", sum(map(len, ent.values())), "in", len(ent), "tables")
allt = [e["event_time"] for v in ev.values() for e in v]
print("event_time range", min(allt), max(allt), "| N =", N, "| any > N:", any(x > N for x in allt))
print("rule times: invalid null stamp ->", [fmt(e["event_time"]) for e in ev["invalid_action_logged"] if e["stamp_null"]],
      "| product_deleted ->", [(e["product_id"], fmt(e["event_time"])) for e in ev["product_deleted"]])
