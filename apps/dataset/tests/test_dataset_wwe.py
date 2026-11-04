COUNTS = {
    "belts_created": 143,
    "card_held": 12639,
    "card_page_scraped": 12639,
    "listing_pages_created": 1270,
    "locations_created": 609,
    "match_held": 77567,
    "match_types_created": 1208,
    "promotions_created": 6,
    "scrape_run": 7,
    "shows_created": 5033,
    "sides_created": 17182
}


def test_wwe_dataset(built):
    manifest, report, types = built("wwe")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 9
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
