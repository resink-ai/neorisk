COUNTS = {
    "aircrafts_created": 9,
    "airports_created": 104,
    "booking_created": 262788,
    "checkin_opened": 17324,
    "flight_arrived": 16715,
    "flight_cancelled": 414,
    "flight_delayed": 41,
    "flight_departed": 16773,
    "flight_scheduled": 33121,
    "passenger_checked_in": 579686,
    "seats_created": 1339,
    "segment_sold": 1045726,
    "ticket_issued": 366733
}


def test_airlines_dataset(built):
    manifest, report, types = built("airlines")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 8
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
