"""Spec §11 exit test: mutation tests. Every seeded fault is caught by the law guarding it."""

import json

import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.errors import LawViolation
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

M = FIXTURES / "mutants"


def test_the_correct_pack_passes_every_law(tmp_path):
    r = run_to_dataset(M, "sample", out_dir=tmp_path / "ok", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert all(v["violations"] == 0 for v in laws.values())
    assert all(v["checked"] > 0 for k, v in laws.items())


@pytest.mark.parametrize("fault,check", [
    (1, "chk.pool_cap"), (2, "chk.credit_le_funded"), (3, "chk.entries_balance"),
    (4, "chk.one_grant"), (5, "chk.holds_freed"), (7, "chk.pool_remaining")])
def test_each_fault_trips_its_law(tmp_path, fault, check):
    with pytest.raises(LawViolation) as e:
        run_to_dataset(M, "sample", [f"fault={fault}"], out_dir=tmp_path / "x", threads=1)
    assert e.value.check_id == check
    assert not (tmp_path / "x").exists()
    if fault == 7:                       # a state law cites the state, seq -1, action -1 (D47)
        assert (e.value.table, e.value.seq, e.value.action_id) == ("state pool.remaining", -1,
                                                                   -1)


def test_an_unanswered_request_trips_pairing(tmp_path):
    with pytest.raises(EngineError, match=r"pool_desk: request claim must be answered exactly "
                                          r"once \(answered 0, returned 2\)"):
        run_to_dataset(M, "sample", ["fault=6"], out_dir=tmp_path / "x", threads=1)


def test_a_soft_law_is_counted_not_fatal(tmp_path):
    r = run_to_dataset(M, "sample", ["fault=8"], out_dir=tmp_path / "soft", threads=1)
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert laws["chk.funded_positive"]["violations"] == 4
    assert laws["chk.funded_positive"]["first"]["detail"] == "amount = -1"


def test_simultaneous_claims_at_the_cap_grant_exactly_one(tmp_path):
    """Review Focus #3: all four accounts claim 100 at t0 and the claims reach the pool at the
    same instant; with cap 100 exactly one is granted, the other three (and every later claim)
    are denied, and `chk.pool_cap` passes."""
    r = run_to_dataset(M, "sample", ["cap=100"], out_dir=tmp_path / "edge", threads=1)
    ev = read_events(r.out_dir)
    granted, denied = ev["granted"], ev["denied"]
    assert granted.height == 1 and granted["remaining_after"].to_list() == [0]
    t = granted["event_time"][0]
    assert (denied["event_time"] == t).sum() == 3            # tied at the same instant
    laws = json.loads((r.out_dir / "manifest.json").read_text())["laws"]
    assert laws["chk.pool_cap"]["violations"] == 0 and laws["chk.pool_cap"]["checked"] == 1
