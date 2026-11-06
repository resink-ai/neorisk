COUNTS = {
    "traders_created": 66,
    "funds_deposited": 264,
    "order_accepted": 9578,
    "order_rejected": 64,
    "trade": 5552,
    "order_filled": 7000,
    "order_cancelled": 1531,
}

TABLES = {"star": 8, "dv": 10, "obt": 3}


def test_crypto_exchange_dataset(built_synthetic):
    manifest, report, types = built_synthetic("crypto_exchange")
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
