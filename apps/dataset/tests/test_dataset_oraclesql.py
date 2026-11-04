COUNTS = {
    "breweries_created": 3,
    "budget_set": 48,
    "channels_dim_created": 2,
    "customers_created": 4,
    "customers_snapshot": 4,
    "demographics_reported": 2,
    "device_counts_reported": 2,
    "employees_created": 14,
    "employees_snapshot": 14,
    "gender_dim_created": 2,
    "heartbeat_received": 14,
    "hire_period_ended": 8,
    "hire_period_started": 15,
    "line_picked": 21,
    "lot_stored": 113,
    "monthly_sales_reported": 360,
    "order_line_added": 18,
    "order_placed": 10,
    "packaging_created": 11,
    "packaging_relations_created": 12,
    "page_counter_read": 120,
    "page_visited": 23,
    "pick_line_planned": 21,
    "picker_arrived": 21,
    "picker_departed": 21,
    "picklist_created": 2,
    "price_quoted": 15,
    "product_groups_created": 4,
    "products_created": 10,
    "products_snapshot": 2,
    "purchase_received": 180,
    "stock_created": 1,
    "web_apps_created": 1,
    "web_pages_created": 4
}


def test_oraclesql_dataset(built):
    manifest, report, types = built("oraclesql")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 38
    assert len(report["queries"]) == 8
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
