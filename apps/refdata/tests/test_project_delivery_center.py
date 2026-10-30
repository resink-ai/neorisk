from conftest import roundtrip

from neorisk_simkit.io import read


def test_delivery_center_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("delivery_center", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["queries"] == 3
    ev = read(ds).events
    assert ev["order_created"].height == 368999
    closed = ev["order_closed"]["order_status"].cast(str).value_counts()
    assert dict(closed.iter_rows()) == {"FINISHED": 352020, "CANCELED": 16979}
    assert ev["payment_recorded"].height == 400834
    assert ev["delivery_assigned"].height == 378843
    assert ev["delivery_closed"].height == 378843 - 223            # DELIVERING stays open
