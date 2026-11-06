COUNTS = {
    "users_created": 600,
    "devices_created": 778,
    "skus_created": 400,
    "orders_created": 151,
    "order_lines_created": 181,
    "user_signed_up": 600,
    "verification_failed": 0,
    "session_started": 2819,
    "product_viewed": 8594,
    "order_placed": 151,
    "checkout_failed": 0,
    "stock_restocked": 402,
    "order_returned": 6,
    "address_changed": 26,
    "referral_bonus_paid": 20,
    "referral_bonus_rejected": 0,
    "reservation_granted": 181,
    "reservation_declined": 0,
    "reservation_committed": 181,
    "reservation_released": 0,
}

TABLES = {"star": 9, "dv": 20, "an": 34}


def test_ecommerce_dataset(built_synthetic):
    manifest, report, types = built_synthetic("ecommerce")
    assert report["ok"]
    assert [r.name for r in report["tables"] + report["questions"] if not r.ok] == []
    per_design: dict[str, int] = {}
    for r in report["tables"]:
        d = r.name.split("_", 1)[0]
        per_design[d] = per_design.get(d, 0) + 1
    assert per_design == TABLES
    assert len(report["questions"]) == 9
    assert manifest["counts"]["questions"] == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
