"""M3 exit: ecommerce + bounty_hunters is thread-, slab- and step-invariant (§10, §12).

Compared across 1 vs 4 threads, `slab_bytes` 4MB vs 64KB and `step` 1d vs 12h (`adapt=false`):
the canonicalized events, the label counts by role and outcome, the machine statistics
(`run_stats.json["machines"]`, every counter) and `late_messages`.

Which IDs are canonicalized (D37):
- The created namespaces of `checks.interference.created_namespaces`: creatable tables and
  `p.ids` names (`order`, `session`, `checkout`, `hold`, `claim`), plus the `partition_id`s of
  the created owner type (`order`). The member table `user` is in `plan.namespaces` but is not
  renamed as a namespace: base user IDs are fixed before the run (members are appended after
  them, D75/D94), so a changed base user ID must fail the comparison.
- Cohort member IDs (the `user` rows with `origin = "member"`) alone are renamed, by first
  appearance in canonical order. Seal numbers them per step by (creating campaign's
  `partition_id`, ordinal) (D75, §12 prefix sum), so in general they depend on step boundaries:
  two campaigns creating members in one 1d step but in different 12h steps can swap order. In
  this workload they come out identical anyway (measured, Task 23), but the test does not rely
  on it.
"""

import json
from pathlib import Path

import polars as pl
import pytest
from conftest import canonicalize_ids

from neorisk_simkit.checks.interference import created_namespaces
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.spec.project import load_project, resolve_run

pytestmark = pytest.mark.large

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=1_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=14d", "run.warmup=1d", *POOLS,
         "bounty_hunters.size=8", "bounty_hunters.arrive_day=1.0",
         "bounty_hunters.arrive_span_days=3.0", "engine.adapt=false"]


def _rename_members(d: Path, events: dict[str, list[dict]], table: str) -> int:
    """Rename the member rows' IDs of `table` (in every event column referencing it) by first
    appearance in canonical order (`event_id` is the canonical position); base IDs are kept.
    Returns the number of member IDs seen."""
    u = pl.read_parquet(d / "entities" / table)
    members = set(u.filter(pl.col("origin") == "member")["id"].to_list())
    refs = {t["name"]: [c["name"] for c in t["columns"] if c.get("ref") == table]
            for t in load_schema(d)["tables"] if t["kind"] == "event"}
    rows = sorted(((r["event_id"], name, r) for name, rs in events.items() for r in rs),
                  key=lambda x: x[0])
    names: dict[int, int] = {}
    for _, name, row in rows:
        for col in refs.get(name, ()):
            v = row[col]
            if v in members:
                row[col] = ("member", names.setdefault(v, len(names)))
    return len(names)


def _run(tmp: Path, name: str, threads: int = 4, extra: tuple = ()):
    overrides = [*SMALL, *extra]
    res = run_to_dataset(EX, "sample", overrides, overlays=["bounty_hunters"],
                         out_dir=tmp / name, threads=threads)
    plan = resolve_run(load_project(EX), "sample", overrides,
                       overlays=["bounty_hunters"]).plan
    created = frozenset(created_namespaces(plan))
    assert "order" in created and "user" not in created
    codes = frozenset(p.ptype_code for p in plan.partitions if p.kind == "owner"
                      and p.table in created and p.table not in plan.member_tables)
    events = canonicalize_ids(res.out_dir, created, codes)
    assert _rename_members(res.out_dir, events, "user") > 0     # members act in every run
    labels = (pl.read_parquet(sorted((res.out_dir / "labels" / "labels_campaign")
                                     .rglob("*.parquet")))
              .group_by("role", "outcome").len().sort("role", "outcome"))
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    return events, labels, stats["machines"], res.manifest["late_messages"], stats


@pytest.fixture(scope="module")
def ref(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("m3inv"), "ref")


@pytest.mark.parametrize("name, threads, extra", [
    ("threads1", 1, ()),
    ("slab64k", 4, ("engine.slab_bytes=64KB",)),
    ("step12h", 4, ("engine.step=12h", "engine.step_min=1h")),
])
def test_logical_records_are_invariant(tmp_path, ref, name, threads, extra):
    events, labels, machines, late, stats = _run(tmp_path, name, threads, extra)
    # each axis really varies the execution (no vacuous pass)
    assert stats["threads"] == threads
    assert stats["steps"] == {"step12h": 30}.get(name, 15) and ref[4]["steps"] == 15
    if name == "slab64k":
        assert stats["retries"] > ref[4]["retries"]                # the small slab fills
    assert labels.height > 0 and machines["hunter"]["spawned"] > 0
    assert events == ref[0]
    assert labels.equals(ref[1])
    assert machines == ref[2] and late == ref[3]
