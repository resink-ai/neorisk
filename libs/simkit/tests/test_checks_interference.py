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
    assert rep["answered_differently"] == {}                         # nothing shared


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
    # base users all claim at t=0, before the gang: the pot answers them alike in both runs
    assert rep["answered_differently"] == {
        "pot": {"changed": {}, "base_only": 0, "with_only": 0, "matched": 6}}


def test_requests_answered_differently_are_counted_by_direction(tmp_path):
    # D79: half the users arrive after the gang drained the pot. Base run: 3 initial users and
    # 2 of the 3 late ones are granted (pot 5 x 1000), the 6th refused. With the gang (4 claims,
    # 2 granted) the late three are all refused: 2 base requests granted -> refused.
    sets = ["initial=0.5"]
    a = run_to_dataset(RING, "sample", sets, out_dir=tmp_path / "a", threads=2).out_dir
    b = run_to_dataset(RING, "sample", sets, overlays=["ring"], out_dir=tmp_path / "b",
                       threads=2).out_dir
    plan = resolve_run(load_project(RING), "sample", sets, overlays=["ring"]).plan
    rep = compare(a, b, plan)
    assert rep["answered_differently"] == {
        "pot": {"changed": {"granted -> refused": 2}, "base_only": 0, "with_only": 0,
                "matched": 6}}
    assert rep["events"]["bonus_paid"] == {"base": 5, "with": 3}
    assert rep["changed_owners"]["bonus_paid"] == 2
    assert rep["exogenous_identical"] is True                 # late arrivals are exogenous


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
    del m["laws"]                                    # no laws entry: nothing shows they hold
    (b / "manifest.json").write_text(json.dumps(m))
    assert compare(a, b, _plan(["ring"]))["laws_ok"] == {"base": True, "with": False}


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
