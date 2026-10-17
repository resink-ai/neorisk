"""D46: additive accumulators: no decision reads them; totals over exported steps."""

import json

import numpy as np
import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import AbiViolation
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.seal import public_ids
from neorisk_simkit.io.step_index import read_step_index
from neorisk_simkit.spec.pack import Pack, PackError
from neorisk_simkit.spec.types import amount, i32, i64


def test_totals_cover_exported_steps_only(tmp_path):
    r = run_to_dataset(FIXTURES / "ledger", "sample", out_dir=tmp_path / "run", threads=1)
    m = json.loads((r.out_dir / "manifest.json").read_text())
    opened = read_events(r.out_dir)["opened"]
    # fees = acct dense id + 1 for every account opened in the exported window
    ids = public_ids(int(m["seed"]), "acct", np.arange(6))
    dense = {int(p): d for d, p in enumerate(ids)}
    assert m["accumulators"] == {"fees": sum(dense[a] + 1 for a in opened["acct_id"])}
    idx = read_step_index(r.out_dir).to_pydict()
    assert sum(idx["acc__fees"]) == m["accumulators"]["fees"]
    assert idx["acc__fees"][0] == 0                     # step 0 is warm-up


@pytest.mark.parametrize("threads, step_h", [(2, 24), (1, 12)])
def test_totals_do_not_depend_on_threads_or_step_length(tmp_path, threads, step_h):
    def run(name, threads, overrides=None):
        r = run_to_dataset(FIXTURES / "ledger", "sample", out_dir=tmp_path / name,
                           threads=threads, engine_overrides=overrides)
        return json.loads((r.out_dir / "manifest.json").read_text())["accumulators"]

    other = run("other", threads, {"step_us": step_h * 3_600_000_000})
    assert other == run("base", 1) and other["fees"] > 0


def test_an_empty_run_writes_zeros(tmp_path):
    """Review Focus #5: `accts=1` opens its single account in warm-up (initial 0.5 of 1 rounds
    to 1; no arrivals are left), so nothing is exported: zero counts, zero postings and every
    accumulator at 0, and the row laws pass vacuously (`checked = 0`)."""
    r = run_to_dataset(FIXTURES / "ledger", "sample", ["accts=1"], out_dir=tmp_path / "empty",
                       threads=1)
    m = json.loads((r.out_dir / "manifest.json").read_text())
    assert sum(m["counts"].values()) == 0
    assert m["posting_counts"] == {"entry": 0}
    assert m["accumulators"] == {"fees": 0}
    for k in ("chk.opened_positive", "chk.entries_balance"):
        assert (m["laws"][k]["checked"], m["laws"][k]["violations"]) == (0, 0), k


def test_an_add_before_reject_is_a_write_in_checked_mode(tmp_path):
    with pytest.raises(AbiViolation, match="process acct_main wrote before returning reject"):
        run_to_dataset(FIXTURES / "ledger", "sample", ["add_then_reject=1"],
                       out_dir=tmp_path / "bad", threads=1, checked=True)


def test_accumulator_types():
    p = Pack("x", 1)
    p.accumulator("a", i64())
    p.accumulator("b", amount(asset="USD"))
    with pytest.raises(PackError, match="accumulator c: type must be i64 or amount"):
        p.accumulator("c", i32())
    with pytest.raises(PackError, match="duplicate accumulator 'a'"):
        p.accumulator("a", i64())
    with pytest.raises(PackError, match="must be an identifier"):
        p.accumulator("d-e", i64())
