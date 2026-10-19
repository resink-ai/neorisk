"""Machines keep the engine's guarantees (§05, §12): retries are invisible, compiled and
uncompiled runs agree, and thread, slab and step changes leave logical records identical."""

import os
import subprocess
import sys
from collections import Counter

import pytest
from conftest import FIXTURES, event_dicts

from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset

CASES = [("mx_basic", []), ("mx_family", []), ("mx_pay", ["latency_ms=300"])]

# The smallest forced capacities validate accepts. `timers` is the largest declared maximum
# among a fixture's processes (mx_nest declares 18: the mother's own timer plus a spawn of up to
# 8 chicks with their timers); `requests` must hold a process's declared requests plus its
# creation messages (mx_payment: 1 capture + 1 receipt creation), else 1. Each record type a
# machine process emits at least twice in these runs is forced to 1 row, so its emits overflow
# the slab (mx_basic's seed sends every parcel: no lost/expired; mx_pay declines once).
FORCED = {
    "mx_basic": {"timers": 2, "requests": 1, **{f"records:{t}": 1 for t in (
        "sent", "delivered", "audited", "audit_failed")}},
    "mx_family": {"timers": 18, "requests": 1, "records:fed": 1, "records:called": 1},
    "mx_pay": {"timers": 2, "requests": 2, **{f"records:{t}": 1 for t in (
        "captured", "closed", "dispute_resolved")}},
}
UNUSED = {("mx_basic", "requests"), ("mx_family", "requests")}   # no request, no creation


def _run(tmp_path, name, overrides, threads=2, **eng):
    return run_to_dataset(FIXTURES / name, "sample", overrides, out_dir=tmp_path / "run",
                          threads=threads, engine_overrides=eng or None).out_dir


def _events(tmp_path, name, overrides, threads=2, **eng):
    return event_dicts(_run(tmp_path, name, overrides, threads, **eng))


@pytest.fixture
def statuses(monkeypatch):
    """Count the runner statuses World handles (each one is a failed reserve and a retry or a
    node refill), as in the S1 ABI proof."""
    seen = Counter()
    real = World.handle_status

    def spy(self, worker, status):
        seen[status] += 1
        return real(self, worker, status)

    monkeypatch.setattr(World, "handle_status", spy)
    return seen


@pytest.mark.parametrize("name, overrides", CASES)
def test_forced_exhaustion_of_each_resource_is_invisible(tmp_path, name, overrides, statuses):
    base = _events(tmp_path / "base", name, overrides)
    assert any(base.values()), "the fixture emits nothing"
    n_base = sum(statuses.values())
    for res, n in FORCED[name].items():
        statuses.clear()
        forced = _events(tmp_path / res.replace(":", "_"), name, overrides,
                         force_capacity={res: n})
        if (name, res) not in UNUSED:
            assert sum(statuses.values()) > n_base, f"{res} was never exhausted"
        assert forced == base, res


def _canon(tmp_path, name, overrides, **eng):
    """D37 comparison (F-25): raw event_id and cause_id depend on step boundaries."""
    from conftest import canonicalize_ids, created_namespaces, created_owner_codes
    out = _run(tmp_path, name, overrides, **eng)
    created = created_namespaces(FIXTURES / name, overrides)
    return canonicalize_ids(out, created,
                            created_owner_codes(FIXTURES / name, overrides, created))


@pytest.mark.parametrize("name, overrides", CASES)
def test_threads_slabs_and_steps_do_not_change_records(tmp_path, name, overrides):
    base = _events(tmp_path / "a", name, overrides, threads=1)
    assert any(base.values()), "the fixture emits nothing"
    assert _events(tmp_path / "b", name, overrides, threads=4) == base
    assert _events(tmp_path / "c", name, overrides, slab_bytes=16 * 1024) == base
    assert (_canon(tmp_path / "d", name, overrides, step_us=2 * 3_600_000_000)
            == _canon(tmp_path / "e", name, overrides))


@pytest.mark.parametrize("name, overrides", CASES[:2])
def test_uncompiled_run_equals_compiled(tmp_path, name, overrides):
    compiled = _events(tmp_path / "jit", name, overrides)
    out = tmp_path / "nojit"
    env = {**os.environ, "NUMBA_DISABLE_JIT": "1"}
    sets = [a for o in overrides for a in ("--set", o)]
    r = subprocess.run([sys.executable, "-m", "datagen.cli", "run", str(FIXTURES / name),
                        "--out", str(out), "--threads", "2", *sets],
                       env=env, capture_output=True, text=True, check=False, timeout=3600)
    assert r.returncode == 0, r.stderr
    assert event_dicts(out) == compiled
