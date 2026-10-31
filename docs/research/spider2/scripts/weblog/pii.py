"""Shape of the personal-looking columns: card numbers, phones, emails, IPs. Prints shapes, never the values
of card numbers. Usage: python3 -I pii.py DB"""
import ipaddress, re, sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)

def shape(v):
    return None if v is None else re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "a", v))

def luhn_ok(digits):
    s, alt = 0, False
    for d in reversed(digits):
        d = int(d)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        s, alt = s + d, not alt
    return s % 10 == 0

print("## mst_users_with_card_number")
for uid, card in con.execute("select user_id, card_number from mst_users_with_card_number order by rowid"):
    if card is None:
        print(uid, "NULL"); continue
    digits = re.sub(r"\D", "", card)
    print(uid, "shape", shape(card), "| length", len(card), "| digits", len(digits),
          "| masked chars", card.count("x"), "| Luhn checkable (>=12 digits)", len(digits) >= 12,
          "| Luhn", luhn_ok(digits) if len(digits) >= 12 else "n/a",
          "| leading digits are a run of consecutive digits",
          all(int(b) - int(a) == 1 for a, b in zip(digits, digits[1:])))
print("\n## app2_mst_users.phone")
for uid, ph in con.execute("select user_id, phone from app2_mst_users"):
    print(uid, shape(ph), "| contains x mask:", "x" in ph)
print("\n## app1_mst_users.email")
for uid, em in con.execute("select user_id, email from app1_mst_users"):
    print(uid, "domain", em.split("@")[1], "| RFC 2606 reserved:", em.split("@")[1] in ("example.com", "example.org", "example.net"))
print("\n## action_log_with_ip.ip")
for ip, n in con.execute("select ip, count(*) from action_log_with_ip group by ip order by min(rowid)"):
    a = ipaddress.ip_address(ip)
    print(ip, n, "| private", a.is_private, "| loopback", a.is_loopback, "| global", a.is_global,
          "| in 192.0.0.0/24", a in ipaddress.ip_network("192.0.0.0/24"))
print("\n## form_error_log.value (dirty inputs, shape)")
for f, fld, et, v in con.execute("select form, field, error_type, value from form_error_log order by rowid"):
    print(f, fld, et, repr(shape(v)))
