COUNTS = {
    "channels_created": 40,
    "delivery_assigned": 378843,
    "delivery_closed": 378620,
    "drivers_created": 4824,
    "drivers_snapshot": 4824,
    "hubs_created": 32,
    "order_closed": 368999,
    "order_created": 368999,
    "order_stage": 2047790,
    "payment_recorded": 400834,
    "stores_created": 951,
    "stores_snapshot": 951
}


def test_delivery_center_dataset(built):
    manifest, report, types = built("delivery_center")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 7
    assert len(report["queries"]) == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
