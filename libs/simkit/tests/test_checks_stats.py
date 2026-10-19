"""D84/D85: expectations grammar and statistical metrics on tiny hand-made datasets."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from neorisk_simkit.checks import stats
from neorisk_simkit.checks.laws import _mix64
from neorisk_simkit.checks.stats import evaluate
from neorisk_simkit.spec.expectations import ExpectationError, load

TS = pa.timestamp("us", tz="UTC")
DAY = 86_400_000_000
EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


def _write(d: Path, name: str, rows: list[dict]) -> None:
    n = len(rows)
    cols = {"event_id": pa.array(range(1, n + 1), pa.int64()),
            "event_type": pa.array([name] * n, pa.string()),
            "event_time": pa.array([r["t"] for r in rows], pa.int64()).cast(TS),
            "lamport": pa.array(range(1, n + 1), pa.int64()),
            "partition_id": pa.array([(r.get("p", 1) << 56) | r["o"] for r in rows], pa.int64()),
            "seq": pa.array([0] * n, pa.int32()),
            "cause_id": pa.nulls(n, pa.int64()),
            "action_id": pa.array([0] * n, pa.int16())}
    for k in sorted({k for r in rows for k in r} - {"t", "o", "p"}):
        vals = [r.get(k) for r in rows]
        kind = next((type(v) for v in vals if v is not None), int)
        cols[k] = pa.array(vals, pa.string() if kind is str else pa.int64())
        if k == "cat":                              # a `cat` column, as the writer types it
            cols[k] = cols[k].dictionary_encode().cast(pa.dictionary(pa.int16(), pa.string()))
    f = d / "events" / name / "date=2026-01-01" / "step-000000.parquet"
    f.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), f)


def _exp(tmp: Path, text: str, overlays=None, cfg=None):
    p = tmp / "expectations.yaml"
    p.write_text(text)
    return load(p, overlays=overlays or {}, cfg=cfg)


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "run"
    starts = [{"t": i * DAY, "o": i, "session_id": i} for i in range(10)]
    _write(d, "session_started", starts)
    _write(d, "checkout_started", [{"t": i * DAY + 5, "o": i, "session_id": i} for i in (1, 3)])
    _write(d, "product_viewed", [{"t": 1, "o": 0, "sku_id": s} for s in [1] * 8 + [2, 3]])
    (d / "manifest.json").write_text(json.dumps({"laws": {"chk.a": {"checked": 3,
                                                                   "violations": 0}}}))
    return d


def test_funnel_share_and_top_share(tmp_path, data):
    exp = _exp(tmp_path, """
defaults: {min_sample: 2}
laws: [{id: chk.a, required: true}, {id: chk.gone, required: true}]
expectations:
  - id: f
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id")
    target: {between: [0.15, 0.25]}
    source: "x"
    required: true
  - id: t
    metric: stat.top_share("product_viewed", by="sku_id", top=0.33)
    target: {gt: 0.7}
    source: "x"
  - id: u
    metric: stat.share("checkout_started", of=["session_started"])
    target: {lt: 0.5}
""")
    res = {r["id"]: r for r in evaluate(exp, data, plan=None, baseline=None)}
    assert res["f"]["value"] == pytest.approx(0.2) and res["f"]["status"] == "pass"
    assert res["t"]["value"] == pytest.approx(0.8) and res["t"]["status"] == "pass"
    assert res["u"]["status"] == "unanchored"
    assert res["chk.a"]["status"] == "pass" and res["chk.gone"]["status"] == "missing"


def test_small_samples_are_inconclusive(tmp_path, data):
    exp = _exp(tmp_path, """
defaults: {min_sample: 100}
expectations:
  - id: f
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id")
    target: {between: [0.0, 1.0]}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=None, baseline=None)
    assert r["status"] == "inconclusive" and r["n_cases"] == 10


def test_within_censors_late_starts(tmp_path, data):
    exp = _exp(tmp_path, """
defaults: {min_sample: 1}
expectations:
  - id: f
    metric: stat.funnel(start="session_started", step="checkout_started", unit="session_id", within="5d")
    target: {between: [0.0, 1.0]}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=None, baseline=None)
    assert r["censored_share"] == pytest.approx(0.5) and r["n_cases"] == 5


def test_metrics_are_calls_not_expressions(tmp_path):
    with pytest.raises(ExpectationError, match="one stat.<name>"):
        _exp(tmp_path, """
expectations:
  - id: bad
    metric: stat.share("a", of=["b"]) + 1
    target: {lt: 1}
    source: "x"
""")


# ---------------------------------------------------------------- beyond the brief's four

FUNNEL = 'stat.funnel(start="session_started", step="checkout_started", unit="session_id"'


def test_the_run_end_comes_from_the_manifest(tmp_path, data):
    """`end_us` in the manifest wins over the last event time (day 7: starts on days 0-2 are
    kept, only session 1 of them converts)."""
    m = json.loads((data / "manifest.json").read_text())
    (data / "manifest.json").write_text(json.dumps({**m, "end_us": 7 * DAY}))
    exp = _exp(tmp_path, f"""
expectations:
  - id: f
    metric: {FUNNEL}, within="5d")
    target: {{between: [0.0, 1.0]}}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=None, baseline=None)
    assert r["n_cases"] == 3 and r["censored_share"] == pytest.approx(0.7)
    assert r["value"] == pytest.approx(1 / 3)


def test_funnel_ci_is_wilson(tmp_path, data):
    exp = _exp(tmp_path, f"""
expectations:
  - id: f
    metric: {FUNNEL})
    target: {{between: [0.0, 1.0]}}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=None, baseline=None)
    z, n, p = 1.959963984540054, 10, 0.2
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z / (1 + z * z / n) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    assert r["ci"] == pytest.approx([c - h, c + h])


def test_within_bounds_the_conversion_window(tmp_path):
    d = tmp_path / "run"
    _write(d, "a", [{"t": 0, "o": 1, "k": 1}, {"t": 0, "o": 2, "k": 2},
                    {"t": 10 * DAY, "o": 3, "k": 3}])
    # k=1 converts after 2 days; k=2 after 4 days (outside 3d); k=3 starts too late (censored)
    _write(d, "b", [{"t": 2 * DAY, "o": 1, "k": 1}, {"t": 4 * DAY, "o": 2, "k": 2},
                    {"t": 10 * DAY, "o": 3, "k": 3}])
    exp = _exp(tmp_path, """
expectations:
  - id: f
    metric: stat.funnel(start="a", step="b", unit="k", within="3d")
    target: {around: 0.5, tolerance: 0.01}
    source: "x"
""")
    (r,) = evaluate(exp, d, plan=None, baseline=None)
    assert r["value"] == pytest.approx(0.5) and r["n_cases"] == 2 and r["status"] == "pass"
    assert r["censored_share"] == pytest.approx(1 / 3)


def test_where_filters_and_nulls_never_match(tmp_path):
    d = tmp_path / "run"
    _write(d, "a", [{"t": 0, "o": i, "k": i, "cat": c}
                    for i, c in enumerate(["x", "x", "y", None, "x"])])
    _write(d, "b", [{"t": 1, "o": 0, "k": 0}, {"t": 1, "o": 3, "k": 3},
                    {"t": 1, "o": 4, "k": None}])
    exp = _exp(tmp_path, """
expectations:
  - id: f
    metric: 'stat.funnel(start="a", step="b", unit="k", where={"cat": "x"})'
    target: {between: [0.3, 0.4]}
    source: "x"
  - id: s
    metric: 'stat.share("a", of=["b"], where={"cat": "x"})'
    target: {between: [0.99, 1.01]}
    source: "x"
""")
    f, s = evaluate(exp, d, plan=None, baseline=None)
    assert f["n_cases"] == 3 and f["value"] == pytest.approx(1 / 3) and f["status"] == "pass"
    assert s["value"] == pytest.approx(1.0) and s["status"] == "pass"


def test_unknown_events_and_columns_are_missing(tmp_path, data):
    exp = _exp(tmp_path, """
expectations:
  - id: e
    metric: stat.share("nope", of=["session_started"])
    target: {lt: 1}
    source: "x"
  - id: c
    metric: 'stat.funnel(start="session_started", step="checkout_started", unit="nope")'
    target: {lt: 1}
    source: "x"
  - id: w
    metric: 'stat.share("checkout_started", of=["session_started"], where={"nope": 1})'
    target: {lt: 1}
    source: "x"
  - id: k
    metric: stat.cohort_size("campaign")
    target: {gt: 0}
    source: "x"
""")
    assert [r["status"] for r in evaluate(exp, data, plan=None, baseline=None)] == ["missing"] * 4


def test_share_ci_is_cluster_robust(tmp_path):
    """Owner 0 has 2 of 2 events, owners 1..3 have 0 of 2: rows 2/8, owners decide the CI."""
    d = tmp_path / "run"
    _write(d, "a", [{"t": 0, "o": 0}, {"t": 0, "o": 0}])
    _write(d, "b", [{"t": 0, "o": o} for o in range(4) for _ in range(2)])
    exp = _exp(tmp_path, """
expectations:
  - id: s
    metric: stat.share("a", of=["b"])
    target: {lt: 0.3}
    source: "x"
""")
    (r,) = evaluate(exp, d, plan=None, baseline=None)
    assert r["value"] == pytest.approx(0.25) and r["n_cases"] == 4
    y, x = np.array([2, 0, 0, 0.0]), np.array([2, 2, 2, 2.0])
    e = y - 0.25 * x
    se = math.sqrt(4 / 3 * (e * e).sum()) / x.sum()
    assert r["ci"] == pytest.approx([0.25 - 1.959963984540054 * se,
                                     0.25 + 1.959963984540054 * se])


def _plan():
    return SimpleNamespace(
        partitions=(SimpleNamespace(name="user", ptype_code=1),
                    SimpleNamespace(name="campaign", ptype_code=2)),
        cohorts=(SimpleNamespace(name="campaign", partition="campaign",
                                 labels="labels_campaign"),))


def _labels(d: Path, rows: list[tuple[int, str]]) -> None:
    f = d / "labels" / "labels_campaign" / "date=2026-01-01" / "step-000000.parquet"
    f.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"target_id": pa.array([r[0] for r in rows], pa.int64()),
                             "role": pa.array([r[1] for r in rows], pa.string())}), f)


def test_quantiles_cohorts_roles_and_sizes(tmp_path):
    d = tmp_path / "run"
    orders = ([{"t": 0, "o": u, "user_id": u, "amount": 100 * u} for u in range(1, 6)]
              + [{"t": 0, "o": 1, "user_id": 1, "amount": 7}]
              + [{"t": 0, "o": 9, "p": 2, "user_id": 100 + k, "amount": 3000 + k}
                 for k in range(5)]
              + [{"t": 0, "o": 8, "p": 2, "user_id": 200, "amount": 5}])
    _write(d, "order_placed", orders)
    # 100..104 are zombies (104 first a hunter, then a zombie: the last row wins), 200 a hunter
    _labels(d, [(104, "hunter"), *[(100 + k, "zombie") for k in range(5)], (200, "hunter")])
    exp = _exp(tmp_path, """
expectations:
  - id: per
    metric: stat.quantiles("order_placed", per="user_id")
    target: {p50: {between: [1, 1]}, p95: {gt: 1}}
    source: "x"
  - id: z
    metric: stat.quantiles("order_placed.amount", cohort="campaign", role="zombie")
    target: {p50: {between: [3001, 3003]}}
    source: "x"
  - id: size
    metric: stat.cohort_size("campaign")
    target: {around: 2, tolerance: 0.0}
    source: "x"
""")
    per, z, size = evaluate(exp, d, plan=_plan(), baseline=None)
    # 11 users: ten with one order, user 1 with two
    assert per["value"] == {"p50": 1, "p95": 2} and per["status"] == "pass"
    assert per["n_cases"] == 7                                  # owners 1..5, 8, 9
    assert z["value"] == {"p50": 3002} and z["status"] == "pass" and z["n_cases"] == 1
    assert size["value"] == 2 and size["status"] == "pass"


def test_distribution_of_gaps(tmp_path):
    d = tmp_path / "run"
    gaps = [1, 2, 3, 4, 10]
    _write(d, "shipped", [{"t": 0, "o": i, "order_id": i} for i in range(6)])
    _write(d, "delivered", [{"t": g * DAY, "o": i, "order_id": i} for i, g in enumerate(gaps)]
           + [{"t": 20 * DAY, "o": 0, "order_id": 0}])
    exp = _exp(tmp_path, """
expectations:
  - id: g
    metric: stat.distribution(between=["shipped", "delivered"], unit="order_id")
    target: {median_days: {between: [3, 4.5]}, p99_days: {lt: 14}}
    source: "x"
""")
    (r,) = evaluate(exp, d, plan=None, baseline=None)
    assert r["value"] == {"median_days": 3.0, "p99_days": 10.0} and r["status"] == "pass"
    assert r["n_cases"] == 5 and r["censored_share"] == pytest.approx(1 / 6)


def test_laws_without_values_are_inconclusive_and_violations_fail(tmp_path, data):
    (data / "manifest.json").write_text(json.dumps({"laws": {
        "chk.a": {"checked": 0, "violations": 0}, "chk.b": {"checked": 5, "violations": 1}}}))
    exp = _exp(tmp_path, "laws: [{id: chk.a, required: true}, {id: chk.b, required: false}]")
    a, b = evaluate(exp, data, plan=None, baseline=None)
    assert (a["status"], a["kind"], a["required"]) == ("inconclusive", "law", True)
    assert (b["status"], b["value"], b["n_cases"]) == ("fail", 1, 5)


def test_interference_needs_a_baseline(tmp_path, data, monkeypatch):
    exp = _exp(tmp_path, """
expectations:
  - id: i
    metric: stat.interference(base="session_started", cause="pool")
    target: {reported: true}
    source: "x"
""")
    (r,) = evaluate(exp, data, plan=_plan(), baseline=None)
    assert r["status"] == "missing"
    seen = {}

    def fake(base_dir, overlay_dir, plan):
        seen["args"] = (base_dir, overlay_dir)
        return {"shared": ["pool"], "events": {"session_started": {"base": 1, "with": 2}}}

    monkeypatch.setattr(stats, "compare", fake)
    (r,) = evaluate(exp, data, plan=_plan(), baseline=tmp_path / "base")
    assert r["status"] == "pass" and r["value"]["shared"] == ["pool"]
    assert seen["args"] == (tmp_path / "base", data)
    monkeypatch.setattr(stats, "compare", lambda a, b, p: {**fake(a, b, p), "shared": []})
    (r,) = evaluate(exp, data, plan=_plan(), baseline=tmp_path / "base")
    assert r["status"] == "fail"


def test_sampling_raises_rates_to_min_sample(tmp_path):
    """sample_rate 0.01 over 40 owners with min_sample 10 samples at rate 0.25: exactly the
    owners whose hash is below 0.25 * 2^64 count, with weight 4 each (one stratum)."""
    d = tmp_path / "run"
    _write(d, "a", [{"t": 0, "o": o, "k": o} for o in range(40)])
    _write(d, "b", [{"t": 1, "o": o, "k": o} for o in range(0, 40, 2)])
    exp = _exp(tmp_path, """
defaults: {min_sample: 10, sample_rate: 0.01}
expectations:
  - id: f
    metric: stat.funnel(start="a", step="b", unit="k")
    target: {between: [0, 1]}
    source: "x"
""")
    (r,) = evaluate(exp, d, plan=None, baseline=None)
    pid = np.array([(1 << 56) | o for o in range(40)], np.int64).view(np.uint64)
    keep = _mix64(pid) < np.uint64(1 << 62)
    owners = np.arange(40)[keep]
    assert 0 < len(owners) < 40 and r["n_cases"] == len(owners)
    assert r["value"] == pytest.approx(np.mean(owners % 2 == 0))


def test_placeholders_and_overlay_sections(tmp_path):
    text = """
expectations:
  - id: base
    metric: stat.cohort_size("campaign")
    target: {between: ["${referral.lo}", 9]}
    source: "x"
overlays:
  bh:
    - id: bh.size
      metric: stat.cohort_size("campaign")
      target: {around: "${bh.size}", tolerance: 0.0}
      source: "overlay config"
  other:
    - id: other.size
      metric: stat.cohort_size("campaign")
      target: {around: "${other.size}", tolerance: 0.0}
"""
    cfg = SimpleNamespace(referral=SimpleNamespace(lo=3))
    exp = _exp(tmp_path, text, overlays={"bh": {"size": 12}}, cfg=cfg)
    assert [x.id for x in exp.items] == ["base", "bh.size"]
    assert exp.items[0].target == {"between": [3, 9]}
    assert exp.items[1].target == {"around": 12, "tolerance": 0.0}
    assert exp.items[1].overlay == "bh" and exp.items[1].required is False
    with pytest.raises(ExpectationError, match="placeholder"):
        _exp(tmp_path, text, overlays={"bh": {"size": 12}}, cfg=None)


@pytest.mark.parametrize("metric", [
    'stat.nope("a")', 'share("a", of=["b"])', 'stat.share("a", of=["b"], **x)',
    'stat.share(a, of=["b"])', 'stat.share("a")', 'stat.share("a", of=["b"], extra=1)',
    'stat.share("a", of=["b"]); 1', 'stat.top_share("a", by="k", top=0.1).x'])
def test_metric_grammar_is_closed(tmp_path, metric):
    with pytest.raises(ExpectationError):
        _exp(tmp_path, f"""
expectations:
  - id: bad
    metric: '{metric}'
    target: {{lt: 1}}
""")


@pytest.mark.parametrize("target", [
    "{p50: {lt: 1}}", "{lt: one}", "{around: 1}", "{between: [1]}", "{reported: false}"])
def test_target_grammar_is_closed(tmp_path, target):
    with pytest.raises(ExpectationError):
        _exp(tmp_path, f"""
expectations:
  - id: bad
    metric: stat.top_share("a", by="k", top=0.1)
    target: {target}
""")


def test_the_ecommerce_expectations_match_the_pack():
    """Task 15 contract: every metric of the real file parses and its law ids are exactly the
    pack's `p.check` ids (spec resolution only, nothing compiles)."""
    from neorisk_simkit.spec.project import load_project, resolve_run

    run = resolve_run(load_project(EX), "sample", [], overlays=["bounty_hunters"])
    exp = load(EX / "specs" / "expectations.yaml", overlays=dict(run.overlays), cfg=run.cfg)
    assert [x.id for x in exp.laws] == [c.id for c in run.plan.checks]
    assert len(exp.laws) == 10 and all(x.required for x in exp.laws)
    assert len(exp.items) == 12 and {x.overlay for x in exp.items} == {None, "bounty_hunters"}
    size = next(x for x in exp.items if x.id == "exp.bh.campaigns")
    assert size.target == {"around": dict(run.overlays)["bounty_hunters"]["size"],
                           "tolerance": 0.0}
    base = load(EX / "specs" / "expectations.yaml", overlays={}, cfg=run.cfg)
    assert len(base.items) == 9 and all(x.overlay is None for x in base.items)
