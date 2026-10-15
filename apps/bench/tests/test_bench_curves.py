import itertools

import numpy as np

from bench.curves import _curves, _pr_step, render_curves


def test_pr_step_is_monotone_in_recall_and_ends_at_full_recall():
    rng = np.random.default_rng(0)
    y = (rng.random(200) < 0.1).astype(int)
    c = _curves(y, rng.random(200))
    xs, ys = _pr_step(c)
    assert all(b >= a for a, b in itertools.pairwise(xs))
    assert xs[-1] == 1.0 and len(xs) == len(ys)


def test_render_curves_both_languages():
    rng = np.random.default_rng(1)
    y = (rng.random(300) < 0.1).astype(int)
    c = _curves(y, rng.random(300))
    keys = ["base", "rare", "sample_1000", "sample_250", "coarse", "leak_echo", "leak_score"]
    res = {"generated_at": "t", "scenarios": {k: c for k in keys}}
    assert "PR / ROC" in render_curves(res, "en")
    assert "<svg" in render_curves(res, "zh")
