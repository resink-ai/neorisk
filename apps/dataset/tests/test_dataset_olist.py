COUNTS = {
    "order_placed": 99441,
    "order_line_added": 112650,
    "payment_recorded": 103886,
    "order_approved": 99281,
    "seller_ship_deadline_set": 100010,
    "order_handed_to_carrier": 97658,
    "order_delivered": 96476,
    "order_status_final": 1857,
    "review_requested": 99224,
    "review_answered": 99224,
    "lead_qualified": 8000,
    "lead_won": 842,
    "sellers_created": 3095,
    "sellers_snapshot": 3095,
    "products_created": 32951,
    "products_snapshot": 32951,
    "geolocation_created": 1000163,
    "translations_created": 71
}


def test_olist_dataset(built):
    manifest, report, types = built("olist")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 11
    assert len(report["queries"]) == 12
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
