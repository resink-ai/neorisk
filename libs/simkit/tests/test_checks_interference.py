"""D78: base rows are identical with and without an overlay that shares nothing."""

from datetime import datetime, timedelta

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.checks.interference import canonical_rows, compare, shared_partitions
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.project import load_project, resolve_run

RING = FIXTURES / "ring"


def _plan(overlays):
    return resolve_run(load_project(RING), "sample", [], overlays=overlays).plan


def test_access_declarations_decide_sharing():
    assert shared_partitions(_plan(["ring"])) == ("pot",)
    assert shared_partitions(_plan(["quiet"])) == ()


def test_a_quiet_overlay_leaves_base_rows_identical(tmp_path):
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", [], overlays=["quiet"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    rep = compare(a, b, _plan(["quiet"]))
    assert rep["shared"] == [] and rep["identical_base_rows"] is True
    assert rep["exogenous_identical"] is True


def test_a_sharing_overlay_reports_interference(tmp_path):
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", [], overlays=["ring"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    rep = compare(a, b, _plan(["ring"]))
    assert rep["shared"] == ["pot"] and rep["identical_base_rows"] is None
    assert rep["exogenous_identical"] is True and rep["laws_ok"] == {"base": True, "with": True}
    assert set(rep["events"]) >= {"signed_up", "bonus_paid"}


def _rows(ids, times, causes, refs):
    t0 = datetime(2026, 3, 1)
    return pl.DataFrame({"event_id": ids, "event_time": [t0 + timedelta(seconds=s) for s in times],
                         "lamport": [1] * len(ids), "partition_id": [0] * len(ids),
                         "seq": list(range(len(ids))), "cause_id": causes, "claim_id": refs})


def test_canonical_rows_number_events_and_causes_by_position():
    # raw event ids and created IDs depend on step boundaries; positions and first-appearance
    # names do not (D37), and a cause maps through the same raw id -> position map (F-01)
    a = {"x": _rows([90, 70], [2, 0], [70, None], [5, 8]), "y": _rows([80], [1], [999], [8])}
    b = {"x": _rows([11, 33], [2, 0], [33, None], [42, 7]), "y": _rows([22], [1], [12], [7])}
    refs = {"x": {"claim_id": "claim"}, "y": {"claim_id": "claim"}}
    ca, cb = canonical_rows(a, {"claim"}, refs), canonical_rows(b, {"claim"}, refs)
    assert all(ca[n].equals(cb[n]) for n in ca)
    assert ca["x"].select("event_id", "cause_id", "claim_id").rows() == [(0, None, 0), (2, 0, 1)]
    assert ca["y"].select("event_id", "cause_id", "claim_id").rows() == [(1, None, 0)]
