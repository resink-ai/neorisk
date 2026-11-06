COUNTS = {
    "accounts_created": 105,
    "genesis_allocated": 100,
    "tx_received": 2996,
    "tx_included": 2932,
    "tx_dropped": 64,
    "transfer_log": 1945,
    "block_produced": 2861,
}

TABLES = {"star": 8, "act": 2, "obt": 3}


def test_layer1_dataset(built_synthetic):
    manifest, report, types = built_synthetic("layer1")
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
