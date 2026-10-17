import hashlib
import json
from datetime import UTC, datetime, timedelta

import polars as pl
import pyarrow.parquet as pq
import pytest
from conftest import FIXTURES, dataset_tree

from neorisk_simkit.io.dataset import ValidationFailed, run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.step_index import read_step_index


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    out = tmp_path_factory.mktemp("mini") / "sample-s7"
    return run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"], out_dir=out)


def test_layout(ds):
    d = ds.out_dir
    for p in ("manifest.json", "run_stats.json", "schema/schema.json", "_index/steps.parquet",
              "entities/user/part-00000.parquet", "entities/item/part-00000.parquet"):
        assert (d / p).exists(), p
    files = sorted((d / "events" / "ping").rglob("*.parquet"))
    assert files and all(f.parent.name.startswith("date=2026-03-0") for f in files)
    assert all(f.name.startswith("step-") and len(f.stem) == len("step-000000") for f in files)


def test_files_sorted_and_dated(ds):
    for f in (ds.out_dir / "events").rglob("*.parquet"):
        t = pl.read_parquet(f)
        key = t.select("event_time", "lamport", "partition_id", "seq")
        assert key.equals(key.sort(["event_time", "lamport", "partition_id", "seq"]))
        day = f.parent.name.removeprefix("date=")
        assert (t["event_time"].dt.strftime("%Y-%m-%d") == day).all()


def test_writer_settings_are_pinned(ds):
    f = next((ds.out_dir / "events" / "took").rglob("*.parquet"))
    md = pq.ParquetFile(f).metadata
    col = md.row_group(0).column(md.schema.names.index("ok"))
    assert col.compression == "ZSTD" and "RLE_DICTIONARY" in col.encodings
    assert md.row_group(0).column(md.schema.names.index("event_time")).statistics is not None
    assert ds.manifest["writer"]["compression_level"] == 3
    assert ds.manifest["writer"]["row_group_size"] == 131_072


def test_manifest_counts_and_hashes(ds):
    m = ds.manifest
    events = read_events(ds.out_dir)
    assert {k: v.height for k, v in events.items()} == {
        k: m["counts"][k] for k in events}
    for entry in m["files"]:
        data = (ds.out_dir / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert m["seed"] == 7 and m["pack"] == "mini" and len(m["pack_revision"]) == 7
    assert "late_messages" in m and m["overrides"] == ["behavior.take_p=0.4"]


def test_step_index_matches_files(ds):
    idx = read_step_index(ds.out_dir)
    assert idx["step"].to_pylist() == sorted(idx["step"].to_pylist())
    assert sum(idx["rows__ping"].to_pylist()) == ds.manifest["counts"]["ping"]


def test_schema_json_lists_common_columns_first(ds):
    doc = json.loads((ds.out_dir / "schema" / "schema.json").read_text())
    ping = next(t for t in doc["tables"] if t["name"] == "ping")
    assert [c["name"] for c in ping["columns"]][:3] == ["event_id", "event_type", "event_time"]
    note_col = next(c for c in ping["columns"] if c["name"] == "note_id")
    assert note_col["nullable"] and note_col["ref"] == "note"


def test_identical_replay_is_byte_identical(ds, tmp_path):
    again = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"],
                           out_dir=tmp_path / "again", threads=1)
    assert dataset_tree(ds.out_dir) == dataset_tree(again.out_dir)


def test_refuses_to_overwrite_without_force(ds):
    with pytest.raises(FileExistsError):
        run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"], out_dir=ds.out_dir)


def test_empty_export_window_still_writes_manifest(tmp_path):
    r = run_to_dataset(FIXTURES / "bad_abi", "sample", ["mode=0"], out_dir=tmp_path / "empty")
    assert (r.out_dir / "manifest.json").exists() and (r.out_dir / "_index/steps.parquet").exists()
    assert r.manifest["counts"]["e"] == 0
    assert not list((r.out_dir / "events").rglob("*.parquet"))


def test_run_stats_carry_engine_counters_and_machine(ds):
    stats = json.loads((ds.out_dir / "run_stats.json").read_text())
    for key in ("rejects", "retries", "late_messages", "continuations"):
        assert stats[key] == ds.stats[key]
    assert isinstance(stats["rejects"], dict) and isinstance(stats["retries"], int)
    assert set(stats["machine"]) == {"arch", "cpus", "ram_bytes"}


def test_validation_failure_message_lists_errors(tmp_path):
    with pytest.raises(ValidationFailed, match="exceed the memory budget") as e:
        run_to_dataset(FIXTURES / "mini", "sample", ["budget.memory=1KB"],
                       out_dir=tmp_path / "refused")
    assert e.value.report.errors and not (tmp_path / "refused").exists()


def test_step_crossing_midnight_and_the_start_instant(tmp_path):
    # mini: start 2026-03-01T00:00Z, warm-up 6h; 5h steps from 02-28T18:00 give 18-23, 23-00
    # (forced boundary at start), then 00-05, 05-10, 10-15, 15-20, 20-01 (crosses midnight)
    r = run_to_dataset(FIXTURES / "mini", "sample", ["engine.step=5h"], out_dir=tmp_path / "m5")
    dirs: dict[tuple[str, str], set[str]] = {}
    for f in (r.out_dir / "events").rglob("*.parquet"):
        dirs.setdefault((f.parent.parent.name, f.stem), set()).add(f.parent.name)
    assert any(len(v) == 2 for v in dirs.values())        # same step-NNNNNN under two date= dirs
    start = datetime(2026, 3, 1, tzinfo=UTC)
    for t in read_events(r.out_dir).values():
        if t.height:
            assert t["event_time"].min() >= start          # exact instants: next test


def test_exact_instants_across_start_step_ends_and_midnight(tmp_path):
    # instants: `mark`s at fixed offsets from start (S) with 5h steps from S-6h, so steps are
    # [S-6h, S-1h), [S-1h, S) (forced), [S, S+5h), [S+5h, S+10h), ... [S+20h, S+25h), [S+25h, ...)
    r = run_to_dataset(FIXTURES / "instants", "sample", out_dir=tmp_path / "i")
    start = datetime(2026, 3, 1, tzinfo=UTC)
    hour, us = timedelta(hours=1), timedelta(microseconds=1)
    expected = {1: start, 2: start + 5 * hour - us, 3: start + 5 * hour, 4: start + 10 * hour,
                5: start + 23.5 * hour, 6: start + 24 * hour, 7: start + 25 * hour}
    marks = read_events(r.out_dir)["mark"]
    # mark 0 sits at start - 1us: simulated (warm-up) but not exported
    assert {m["n"]: m["event_time"] for m in marks.to_dicts()} == expected
    assert marks["n"].to_list() == sorted(expected)                    # canonical order

    idx = read_step_index(r.out_dir).to_pylist()
    step_of = {}
    for f in (r.out_dir / "events" / "mark").rglob("*.parquet"):
        step = int(f.stem.removeprefix("step-"))
        for n in pl.read_parquet(f)["n"]:
            step_of[n] = (step, f.parent.name)
    for n, t in expected.items():
        row = idx[step_of[n][0]]
        assert row["step"] == step_of[n][0] and row["t_start"] <= t < row["t_end"]
    assert idx[step_of[1][0]]["t_start"] == start                      # t == start is exported
    assert idx[step_of[2][0]]["t_end"] == expected[3]                  # S+5h-1us ends the step...
    assert idx[step_of[3][0]]["t_start"] == expected[3]                # ...S+5h opens the next
    assert step_of[2][0] + 1 == step_of[3][0]
    assert idx[step_of[4][0]]["t_start"] == expected[4]
    assert idx[step_of[7][0]]["t_start"] == expected[7]                # S+25h: step end -> next
    assert step_of[6][0] + 1 == step_of[7][0]
    # the step [S+20h, S+25h) crosses midnight: one step number under two date= dirs
    assert step_of[5][0] == step_of[6][0]
    assert (step_of[5][1], step_of[6][1]) == ("date=2026-03-01", "date=2026-03-02")
    assert read_step_index(r.out_dir)["rows__mark"].to_pylist()[:2] == [0, 0]   # warm-up steps


def test_force_keeps_the_old_folder_until_the_new_one_is_in_place(tmp_path, monkeypatch):
    out = tmp_path / "run"
    run_to_dataset(FIXTURES / "mini", "sample", ["users=20"], out_dir=out)
    (out / "marker.txt").write_text("old")
    real_rename = type(out).rename

    def failing(self, target):
        if self.name.endswith(".partial"):
            raise OSError("disk full")
        return real_rename(self, target)

    monkeypatch.setattr(type(out), "rename", failing)
    with pytest.raises(OSError, match="disk full"):
        run_to_dataset(FIXTURES / "mini", "sample", ["users=20"], out_dir=out, force=True)
    monkeypatch.undo()
    assert (out / "marker.txt").read_text() == "old"
    assert (out / "manifest.json").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run"]
    run_to_dataset(FIXTURES / "mini", "sample", ["users=20"], out_dir=out, force=True)
    assert not (out / "marker.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run"]


def test_failed_cleanup_of_the_old_folder_does_not_fail_the_run(tmp_path, monkeypatch):
    """Once the new dataset is in place, failing to delete the set-aside `.old` folder is not
    a failed run."""
    import shutil

    from neorisk_simkit.io import dataset

    out = tmp_path / "run"
    run_to_dataset(FIXTURES / "mini", "sample", ["users=20"], out_dir=out)
    (out / "marker.txt").write_text("old")
    real_rmtree = shutil.rmtree

    def failing(path, ignore_errors=False, **kw):
        if str(path).endswith(".old"):
            if ignore_errors:
                return None
            raise OSError("busy")
        return real_rmtree(path, ignore_errors=ignore_errors, **kw)

    monkeypatch.setattr(dataset.shutil, "rmtree", failing)
    r = run_to_dataset(FIXTURES / "mini", "sample", ["users=20"], out_dir=out, force=True)
    assert r.out_dir == out and (out / "manifest.json").exists()
    assert not (out / "marker.txt").exists()


def _reference_bytes(tmp_path, parts, run):
    """What the one-shot writer produces for the concatenation of `parts`."""
    import pyarrow as pa

    from neorisk_simkit.io.writer import plan_columns, write_parquet, writer_options
    table = pa.concat_tables(parts) if len(parts) > 1 else parts[0]
    write_parquet(tmp_path, "ref.parquet", table,
                  writer_options(run.writer, *plan_columns(run.plan)))
    return (tmp_path / "ref.parquet").read_bytes()


def test_entities_stream_per_step_in_full_row_groups(tmp_path):
    """Entity rows are written as they are sealed: at most one partial row group per table
    stays in memory, and every file is byte-identical to writing the whole table at the end."""
    from conftest import make_run

    from neorisk_simkit.engine.run import Simulation
    from neorisk_simkit.io.entities import EntityWriter

    run = make_run("mini", ["writer.row_group_rows=64"])
    sim = Simulation(run, threads=1)
    ew = EntityWriter(tmp_path / "run", run.writer, run.plan)
    parts: dict[str, list] = {}

    def add(tables):
        ew.add(tables)
        for name, t in tables.items():
            if t.num_rows or name not in parts:
                parts.setdefault(name, []).append(t)
        assert all(ew.buffered_rows(name) < 64 for name in parts)

    add(sim.static_entities())
    for sealed in sim.steps():
        add(sealed.entities)
    assert len([t for t in parts["note"] if t.num_rows]) > 3
    assert sum(t.num_rows for t in parts["note"]) > 3 * 64
    assert ew.counts() == {n: sum(t.num_rows for t in ts) for n, ts in sorted(parts.items())}
    entries = ew.close()
    assert [e.path for e in entries] == [f"entities/{n}/part-00000.parquet" for n in sorted(parts)]
    for e in entries:
        name = e.path.split("/")[1]
        data = (tmp_path / "run" / e.path).read_bytes()
        assert data == _reference_bytes(tmp_path, parts[name], run), name
        assert e.sha256 == hashlib.sha256(data).hexdigest()
        assert e.rows == sum(t.num_rows for t in parts[name])


@pytest.mark.parametrize("sizes", [[0], [0, 0], [0, 64], [64, 64], [30, 40, 0, 58], [200, 1]])
def test_entity_stream_edges_match_the_one_shot_writer(tmp_path, sizes):
    import pyarrow as pa
    from conftest import make_run

    from neorisk_simkit.io.entities import EntityWriter

    run = make_run("mini", ["writer.row_group_rows=64"])
    cats = pa.array(["a", "b"], pa.string())
    parts, start = [], 0
    for n in sizes:
        idx = pa.array([i % 2 for i in range(start, start + n)], pa.int16())
        parts.append(pa.table({"id": pa.array(range(start, start + n), pa.int64()),
                               "tier": pa.DictionaryArray.from_arrays(idx, cats)}))
        start += n
    ew = EntityWriter(tmp_path / "run", run.writer, run.plan)
    for t in parts:
        ew.add({"user": t})
        assert ew.buffered_rows("user") < 64
    (entry,) = ew.close()
    kept = [t for i, t in enumerate(parts) if t.num_rows or i == 0]
    assert (tmp_path / "run" / entry.path).read_bytes() == _reference_bytes(tmp_path, kept, run)


def _three_streams(tmp_path):
    import pyarrow as pa
    from conftest import make_run

    from neorisk_simkit.io.entities import EntityWriter

    run = make_run("mini")
    ew = EntityWriter(tmp_path / "run", run.writer, run.plan)
    ew.add({n: pa.table({"id": pa.array([1, 2], pa.int64())}) for n in ("a", "b", "c")})
    return ew


def test_entity_abort_tries_every_stream_and_never_raises(tmp_path, monkeypatch):
    ew = _three_streams(tmp_path)
    called = []
    for name, stream in ew._streams.items():
        def abort(name=name):
            called.append(name)
            if name == "b":
                raise OSError("disk gone")
        monkeypatch.setattr(stream, "abort", abort)
    ew.abort()                                       # must not mask the run's own failure
    assert sorted(called) == ["a", "b", "c"]


def test_entity_close_failure_aborts_the_other_streams(tmp_path, monkeypatch):
    ew = _three_streams(tmp_path)
    aborted = []
    for name, stream in ew._streams.items():
        monkeypatch.setattr(stream, "abort", lambda name=name: aborted.append(name))
    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(ew._streams["b"], "close", boom)
    with pytest.raises(OSError, match="disk full"):
        ew.close()
    assert sorted(aborted) == ["b", "c"]             # "a" closed cleanly before the failure
