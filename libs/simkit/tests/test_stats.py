"""expectations.yaml: parsing, targets, inconclusive samples, CIs across held-out seeds."""

from pathlib import Path

import pytest

from neorisk_simkit.checks import stats
from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project

EX = Path(__file__).resolve().parents[3] / "examples"


def _out(project, *sets, overlays=()):
    pr = load_project(EX / project)
    s = pr.settings(None, list(sets), list(overlays))
    return simulate(pr.plan(s.overlays), s.config, s.run)


def test_metric_parsing_is_literal_only():
    assert stats.parse_metric('stat.share("a", of=["a", "b"])') == ("share", ["a"],
                                                                     {"of": ["a", "b"]})
    for bad in ('share("a")', 'stat.nope("a")', 'stat.share(__import__("os"))', "stat.share("):
        with pytest.raises(stats.ExpectationError):
            stats.parse_metric(bad)


def test_targets():
    assert stats.meets(0.5, {"between": [0.4, 0.6]})
    assert not stats.meets(0.7, {"between": [0.4, 0.6]})
    assert stats.meets(0.1, {"lt": 0.2}) and stats.meets(3, {"gt": 2})
    assert stats.meets(0.052, {"around": 0.05, "tolerance": 0.1})
    assert stats.meets(1.0, {"reported": True}) is None
    assert not stats.meets(float("nan"), {"lt": 1})


@pytest.mark.parametrize(("project", "sets", "overlays"), [
    ("ecommerce", ["users=2000"], ["bounty_hunters"]),
    ("payments", [], []),
])
def test_example_expectations_hold_with_held_out_seed_intervals(project, sets, overlays):
    main = _out(project, *sets, overlays=overlays)
    held = [_out(project, *sets, f"run.seed={s}", overlays=overlays) for s in (101, 102)]
    res = stats.check_expectations(main, EX / project / "specs" / "expectations.yaml", held)
    assert res and all(r.status == "pass" for r in res), [r.as_dict() for r in res
                                                          if r.status != "pass"]
    ci = [r.metric["ci95"] for r in res if not isinstance(r.metric["value"], dict)]
    assert all(lo <= hi for lo, hi in ci)
    if overlays:
        assert {"exp.hunters", "exp.zombies"} <= {r.name for r in res}


def test_small_samples_are_inconclusive_and_off_targets_fail(tmp_path):
    out = _out("ecommerce", "users=100", "run.days=10")
    f = tmp_path / "e.yaml"
    f.write_text("""
defaults: {min_sample: 1000}
expectations:
  - {id: a, metric: 'stat.funnel("user_signed_up", "order_placed", unit="user_id")',
     target: {between: [0, 1]}, required: true}
  - {id: b, metric: 'stat.count("user_signed_up")', target: {gt: 10**9}, min_sample: 1}
""".replace("10**9", "1000000000"))
    a, b = stats.check_expectations(out, f)
    assert a.status == "inconclusive" and b.status == "fail"
