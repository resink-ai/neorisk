"""The legacy fraud export keeps the shape bench was built on (pinned from the export of the
hand-coded scenario this pack replaced), and its planted signal."""

from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.engine import simulate
from neorisk_simkit.io.legacy import legacy_fraud, rescore
from neorisk_simkit.project import load_project

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
I, F, S = pl.Int64, pl.Float64, pl.String
EVENTS = {"event_id": S, "event_time": pl.Datetime("us"), "event_type": I, "user_id": I,
          "device_id": I, "product_id": I, "inviter_id": I, "amount": F, "currency": I,
          "referral_bonus": F, "user_age_bucket": I, "user_segment": I, "user_state": I,
          "device_os": I, "device_model": I, "product_category": I, "product_price": F,
          "label": I}
GOLDEN = (["event_id"]
          + [f"u_amt_{a}_{w}d" for w in (7, 14, 30) for a in ("count", "sum", "mean", "max",
                                                                "min")]
          + ["dev_users_n_unique_7d"]
          + [f"inv_bonus_{a}_{w}d" for w in (7, 14, 30) for a in ("count", "sum", "mean", "max")]
          + [f"invr_bonus_{a}_{w}d" for w in (7, 14, 30) for a in ("count", "sum", "mean",
                                                                   "max")]
          + ["amt_ratio_30d", "invitee_is_zombie", "actor_role", "score"])
CODES = {"user_age_bucket": 5, "user_segment": 4, "user_state": 8, "device_os": 4,
         "device_model": 3, "product_category": 6}


def test_legacy_export_shape_is_pinned():
    pr = load_project(ECOM)
    s = pr.settings("legacy", ["users=800"], ["bounty_hunters"])
    ds = legacy_fraud(simulate(pr.plan(s.overlays), s.config, s.run))
    assert dict(ds.events.schema) == EVENTS
    assert ds.golden.columns == GOLDEN
    for c, n in CODES.items():
        vals = ds.events[c].drop_nulls()
        assert vals.min() >= 0 and vals.max() < n, c
    assert set(ds.events["event_type"]) == {0, 1}
    assert ds.events["event_time"].is_sorted()
    assert set(ds.golden["actor_role"]) <= {0, 1, 2}
    assert "feature_allowlist" in ds.meta and "label" not in ds.meta["feature_allowlist"]


def test_rescore_samples_calibrated_labels_from_the_scorer():
    pr = load_project(ECOM)
    s = pr.settings("legacy", [], ["bounty_hunters"])
    ds = legacy_fraud(simulate(pr.plan(s.overlays), s.config, s.run))
    for kind in ("xgb", "mlp"):
        a, b = rescore(ds, kind, bad_rate=0.1, seed=3), rescore(ds, kind, bad_rate=0.1, seed=3)
        assert a.events.equals(b.events) and a.golden.equals(b.golden)
        assert dict(a.events.schema) == EVENTS and a.golden.columns == GOLDEN
        p = a.golden["score"]
        assert abs(p.mean() - 0.1) < 1e-3 and 0 < p.min() and p.max() < 1
        assert set(a.events["label"]) == {0, 1}
        assert a.meta["labels"]["scorer"] == kind and "labels" not in ds.meta
        assert not a.events["label"].equals(rescore(ds, kind, 0.1, seed=4).events["label"])
    ring = ds.golden["actor_role"] > 0
    p = rescore(ds, "xgb", 0.1, seed=3).golden["score"]
    assert p.filter(ring).mean() > 2 * p.filter(~ring).mean()   # the planted ring signal
    with pytest.raises(ValueError, match="unknown scorer"):
        rescore(ds, "gbm")
