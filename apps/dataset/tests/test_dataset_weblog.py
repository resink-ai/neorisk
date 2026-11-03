COUNTS = {
    "access_logged": 30,
    "action_logged": 120,
    "action_with_ip_logged": 12,
    "noisy_action_logged": 0,
    "dup_action_logged": 11,
    "invalid_action_logged": 7,
    "activity_logged": 244,
    "read_logged": 15,
    "form_viewed": 45,
    "form_error_logged": 8,
    "purchase_logged": 5,
    "user_registered": 320,
    "category_named": 8,
    "product_updated": 8,
    "product_deleted": 1,
    "app1_users_created": 2,
    "app2_users_created": 2,
    "user_cards_created": 3,
    "product_sales_created": 10
}


def test_weblog_dataset(built):
    manifest, report, types = built("weblog")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 19
    assert len(report["queries"]) == 5
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
