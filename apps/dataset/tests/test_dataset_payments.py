COUNTS = {
    "customers_created": 400,
    "cards_created": 400,
    "merchants_created": 120,
    "payments_created": 4761,
    "credit_line_opened": 400,
    "statement_paid": 399,
    "payment_declined": 109,
    "payment_authorized": 4662,
    "payment_captured": 4335,
    "capture_replayed": 220,
    "payment_expired": 265,
    "refund_issued": 438,
    "refund_failed": 4,
    "refund_refused": 6,
    "dispute_opened": 16,
    "dispute_resolved": 2,
    "settlement_posted": 1974,
    "hold_placed": 5203,
    "hold_committed": 5100,
    "hold_released": 103,
}

TABLES = {"star": 14, "dv": 22, "obt": 4}


def test_payments_dataset(built_synthetic):
    manifest, report, types = built_synthetic("payments")
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
