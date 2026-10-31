from conftest import roundtrip

from neorisk_simkit.io import read

COUNTS = {"order_placed": 99441, "order_line_added": 112650, "payment_recorded": 103886,
          "order_approved": 99281, "seller_ship_deadline_set": 100010,
          "order_handed_to_carrier": 97658, "order_delivered": 96476,
          "order_status_final": 1857, "review_requested": 99224, "review_answered": 99224,
          "lead_qualified": 8000, "lead_won": 842}


def test_olist_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("olist", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["queries"] == 12
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == COUNTS
    assert {k: v.height for k, v in run.entities.items()} == {
        "sellers": 3095, "products": 32951, "geolocation": 1000163, "translations": 71}
