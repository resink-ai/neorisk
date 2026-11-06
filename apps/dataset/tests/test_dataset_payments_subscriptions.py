COUNTS = {
    "subscribers_created": 500,
    "subscription_started": 500,
    "trial_converted": 376,
    "invoice_paid": 835,
    "charge_failed": 85,
    "subscription_cancelled": 156,
}

TABLES = {"star": 7, "act": 2, "an": 21}


def test_payments_subscriptions_dataset(built_synthetic):
    manifest, report, types = built_synthetic("payments_subscriptions")
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
