from conftest import roundtrip

from neorisk_simkit.io import read

COUNTS = {"booking_created": 262788, "ticket_issued": 366733, "segment_sold": 1045726,
          "passenger_checked_in": 579686, "flight_scheduled": 33121}


def test_airlines_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("airlines", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["queries"] == 2
    ev = read(ds).events
    assert {k: ev[k].height for k in COUNTS} == COUNTS
    assert ev["flight_cancelled"].height == 414
    last = max(df["event_time"].max() for df in ev.values() if df.height)
    assert last.isoformat() <= "2017-08-15T18:00:00+00:00"          # the log ends at N
