COUNTS = {
    "categories_created": 8,
    "customergroupthreshold_created": 4,
    "customers_created": 91,
    "customers_snapshot": 91,
    "employee_hired": 9,
    "employees_snapshot": 9,
    "employeeterritories_created": 49,
    "order_line_added": 2155,
    "order_placed": 830,
    "order_shipped": 809,
    "products_created": 77,
    "products_snapshot": 77,
    "region_created": 4,
    "shippers_created": 6,
    "shippers_snapshot": 6,
    "suppliers_created": 29,
    "suppliers_snapshot": 29,
    "territories_created": 53,
    "usstates_created": 51
}


def test_northwind_dataset(built):
    manifest, report, types = built("northwind")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 15
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
