"""The snapshot contract: `<entity>_snapshot` events keyed by their entity, one per key, all
at one time N that no other event follows."""

import json
from datetime import UTC, datetime, timedelta

import polars as pl

from dataset.snapshots import check_snapshots

N = datetime(2022, 4, 5, tzinfo=UTC)


def make_log(tmp_path, rows, entities=("companies",)):
    """A built-version folder: `rows` are (event_time, event_type, entity_type, entity_key)."""
    events = [{"name": f"{e}_created", "kind": "entity_created", "entity": e, "key": "id",
               "fields": []} for e in entities]
    names = sorted({r[1] for r in rows} - {e["name"] for e in events})
    events += [{"name": n, "kind": "event", "entity": None, "key": None, "fields": []}
               for n in names]
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "events.json").write_text(
        json.dumps({"format": 1, "schema_version": 1, "events": events}))
    (tmp_path / "log").mkdir()
    pl.DataFrame({"seq": range(1, len(rows) + 1),
                  "event_time": [r[0] for r in rows],
                  "event_type": [r[1] for r in rows], "entity_type": [r[2] for r in rows],
                  "entity_key": [r[3] for r in rows], "schema_version": [1] * len(rows),
                  "payload": ["{}"] * len(rows)},
                 schema_overrides={"event_time": pl.Datetime("us", "UTC"),
                                   "schema_version": pl.Int32}
                 ).write_parquet(tmp_path / "log" / "part-00000.parquet")
    return tmp_path


def base(n=N):
    return [(n - timedelta(days=9), "companies_created", "companies", "7"),
            (n - timedelta(days=8), "companies_created", "companies", "8"),
            (n - timedelta(days=1), "deal_closed", "companies", "7"),
            (n, "companies_snapshot", "companies", "7"),
            (n, "companies_snapshot", "companies", "8")]


def test_valid_snapshot_passes(tmp_path):
    assert check_snapshots(make_log(tmp_path, base())) == []


def test_no_snapshot_events_passes(tmp_path):
    assert check_snapshots(make_log(tmp_path, base()[:3])) == []


def test_snapshot_owner_must_be_its_entity(tmp_path):
    rows = base()
    rows[3] = (N, "companies_snapshot", "company_id", "7")
    problems = check_snapshots(make_log(tmp_path, rows))
    assert len(problems) == 1
    assert "companies_snapshot" in problems[0] and "entity_type" in problems[0]


def test_snapshot_time_after_every_event(tmp_path):
    late = base() + [(N + timedelta(seconds=1), "deal_closed", "companies", "8")]
    assert any("after the snapshot time" in p for p in check_snapshots(make_log(tmp_path, late)))


def test_snapshots_share_one_time(tmp_path):
    rows = base()
    rows[4] = (N - timedelta(hours=1), "companies_snapshot", "companies", "8")
    assert any("one snapshot time" in p for p in check_snapshots(make_log(tmp_path, rows)))


def test_one_snapshot_per_key(tmp_path):
    rows = base() + [(N, "companies_snapshot", "companies", "7")]
    problems = check_snapshots(make_log(tmp_path, rows))
    assert any("'7'" in p and "companies_snapshot" in p for p in problems)


def test_snapshot_key_never_null(tmp_path):
    rows = base()
    rows[4] = (N, "companies_snapshot", "companies", None)
    assert any("null" in p for p in check_snapshots(make_log(tmp_path, rows)))


def test_snapshot_for_unknown_entity(tmp_path):
    rows = base() + [(N, "compnies_snapshot", "compnies", "7")]
    assert any("unknown entity" in p for p in check_snapshots(make_log(tmp_path, rows)))
