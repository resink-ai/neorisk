COUNTS = {
    "albums_created": 347,
    "artists_created": 275,
    "customers_created": 59,
    "customers_snapshot": 59,
    "employee_hired": 8,
    "employees_snapshot": 8,
    "genres_created": 25,
    "invoice_issued": 412,
    "invoice_line_added": 2240,
    "media_types_created": 5,
    "playlist_track_created": 8715,
    "playlists_created": 18,
    "tracks_created": 3503,
    "tracks_snapshot": 3503
}


def test_music_dataset(built):
    manifest, report, types = built("music")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 11
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
