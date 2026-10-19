"""D78: base rows are identical with and without an overlay that shares nothing."""

import json
import shutil
from datetime import datetime, timedelta

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.checks import interference
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
    assert rep["events"]["signed_up"] == {"base": 6, "with": 6}      # base rows were compared
    assert set(rep["changed_owners"].values()) == {0}


def test_a_sharing_overlay_reports_interference(tmp_path):
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", [], overlays=["ring"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    rep = compare(a, b, _plan(["ring"]))
    assert rep["shared"] == ["pot"] and rep["identical_base_rows"] is None
    assert rep["exogenous_identical"] is True and rep["laws_ok"] == {"base": True, "with": True}
    assert set(rep["events"]) >= {"signed_up", "bonus_paid"}
    assert rep["events"]["refused"] == {"base": 1, "with": 5}       # the pot serves the gang
    assert rep["changed_owners"]["refused"] == 1 and rep["first_contact"] is not None


def test_the_comparison_fails_when_base_rows_differ(tmp_path, monkeypatch):
    # the ring overlay changes the pot's answers; declared as sharing nothing, both verdicts
    # must turn False (the equality is not vacuous), and a required law violation shows
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", [], overlays=["ring"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    m = json.loads((b / "manifest.json").read_text())
    m["laws"]["chk.x"] = {"required": True, "violations": 1}
    (b / "manifest.json").write_text(json.dumps(m))
    monkeypatch.setattr(interference, "shared_partitions", lambda plan: ())
    rep = compare(a, b, _plan(["ring"]))
    assert rep["identical_base_rows"] is False and rep["exogenous_identical"] is False
    assert rep["laws_ok"] == {"base": True, "with": False}


def test_moved_base_user_ids_are_a_difference(tmp_path):
    # base user IDs are fixed before the run (members come after them, D94): `user` is a
    # member table of the overlay plan, yet it is never canonicalized away
    a = run_to_dataset(RING, "sample", [], out_dir=tmp_path / "a", threads=2).out_dir
    b = tmp_path / "b"
    shutil.copytree(a, b)
    users = {"signed_up": ("user_id", "invited_by"), "bonus_paid": ("user_id",),
             "granted": ("who",), "refused": ("who",), "refunded": ("who",)}
    for name, cols in users.items():
        for f in (b / "events" / name).glob("date=*/step-*.parquet"):
            t = pl.read_parquet(f)
            t.with_columns(pl.col(c) + 1 for c in cols).write_parquet(f)
    plan = _plan(["quiet"])
    assert "user" in plan.namespaces
    assert compare(a, a, plan)["identical_base_rows"] is True
    assert compare(a, b, plan)["identical_base_rows"] is False


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
