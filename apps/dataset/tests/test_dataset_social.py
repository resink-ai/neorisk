COUNTS = {
    "users_created": 500,
    "follows_created": 15364,
    "post_created": 306,
    "post_viewed": 8076,
    "post_liked": 1184,
    "post_reposted": 462,
}

TABLES = {"star": 7, "dv": 9, "act": 2}


def test_social_dataset(built_synthetic):
    manifest, report, types = built_synthetic("social")
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
