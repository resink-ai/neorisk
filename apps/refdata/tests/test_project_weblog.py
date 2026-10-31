from conftest import roundtrip

from neorisk_simkit.io import read


def test_weblog_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("weblog", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 19
    assert summary["queries"] == 5
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "access_logged": 30, "action_logged": 120, "action_with_ip_logged": 12,
        "noisy_action_logged": 0, "dup_action_logged": 11, "invalid_action_logged": 7,
        "activity_logged": 244, "read_logged": 15, "form_viewed": 45, "form_error_logged": 8,
        "purchase_logged": 5, "user_registered": 320, "category_named": 8,
        "product_updated": 8, "product_deleted": 1}
    assert {k: v.height for k, v in run.entities.items()} == {
        "app1_users": 2, "app2_users": 2, "user_cards": 3, "product_sales": 10}
    assert run.events["access_logged"]["shifted"].sum() == 19
