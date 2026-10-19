"""D88: the e-commerce pack + bounty_hunters overlay, exported through the legacy adapter, has
the properties today's fraud dataset has, and bench runs on it."""

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from bench.allowlist import resolve_allowlist
from bench.features import build_features
from bench.runner import load_events, run
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.legacy import legacy_fraud
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.schema.schema_json import load_schema

pytestmark = pytest.mark.large

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"
SMALL = ["users=3000", "run.span=40d"]


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("legacy")
    res = run_to_dataset(EX, "legacy", SMALL, out_dir=tmp / "run", threads=4)
    from datagen.cli import main
    assert main(["export", str(res.out_dir), "--legacy-fraud", "--out", str(tmp / "fraud")]) == 0
    return res.out_dir, tmp / "fraud"


@pytest.fixture(scope="module")
def ds(dirs):
    return legacy_fraud(dirs[0])


def test_export_is_deterministic(dirs, ds):
    again = legacy_fraud(dirs[0])
    assert again.events.equals(ds.events) and again.golden.equals(ds.golden)
    # the CLI wrote the same frames
    assert pl.read_parquet(dirs[1] / "events.parquet").equals(ds.events)
    assert pl.read_parquet(dirs[1] / "golden.parquet").equals(ds.golden)


def test_shape_and_no_golden_in_events(ds):
    golden_cols = set(ds.golden.columns) - {"event_id"}
    assert not golden_cols & set(ds.events.columns)
    assert set(ds.events["event_id"]) == set(ds.golden["event_id"])
    for c in ("event_time", "event_type", "user_id", "device_id", "amount", "label",
              "inviter_id", "referral_bonus", "user_state"):
        assert c in ds.events.columns, c


def test_columns_and_meta(dirs, ds):
    assert ds.events.columns == [
        "event_id", "event_time", "event_type", "user_id", "device_id", "product_id",
        "inviter_id", "amount", "currency", "referral_bonus", "user_age_bucket", "user_segment",
        "user_state", "device_os", "device_model", "product_category", "product_price", "label"]
    w = [7, 14, 30]
    assert ds.golden.columns == [
        "event_id",
        *(f"u_amt_{a}_{d}d" for d in w for a in ("count", "sum", "mean", "max", "min")),
        "dev_users_n_unique_7d",
        *(f"inv_bonus_{a}_{d}d" for d in w for a in ("count", "sum", "mean", "max")),
        *(f"invr_bonus_{a}_{d}d" for d in w for a in ("count", "sum", "mean", "max")),
        "amt_ratio_30d", "invitee_is_zombie", "actor_role", "score"]
    assert ds.events["event_id"].str.starts_with("order_placed:").sum() == ds.events.filter(
        pl.col("event_type") == 0).height
    assert ds.events.filter(pl.col("event_type") == 1)["event_id"].str.starts_with(
        "referral_bonus_paid:").all()
    assert set(ds.events["event_type"].unique()) == {0, 1}
    assert ds.golden["score"].dtype == pl.Float64
    assert ds.golden["score"].equals(ds.events["label"].cast(pl.Float64).alias("score"))
    meta = json.loads((dirs[1] / "meta.json").read_text())
    assert meta["scenario"] == "ecommerce+bounty_hunters" and meta["seed"] == 42
    assert meta["source"]["pack"] == "ecommerce" and meta["source"]["revision"]
    assert "bounty_hunters" in meta["source"]["overlays"]
    assert meta["source"]["run"] == "legacy-s42+bounty_hunters"
    assert meta["feature_allowlist"] == [
        c for c, t in ds.events.schema.items()
        if t.is_numeric() and c != "label" and not c.endswith("_id")]
    # amounts in dollars; currency only on orders, referral_bonus only on invites
    txn, inv = (ds.events.filter(pl.col("event_type") == k) for k in (0, 1))
    assert txn["amount"].null_count() == 0 and inv["amount"].null_count() == inv.height
    assert (txn["currency"] == 0).all() and txn["currency"].null_count() == 0
    assert inv["currency"].null_count() == inv.height
    assert inv["referral_bonus"].null_count() == 0 and (inv["referral_bonus"] > 0).all()
    assert txn["referral_bonus"].null_count() == txn.height
    for c in ("user_age_bucket", "user_segment", "user_state", "device_id", "device_os",
              "device_model"):
        assert ds.events[c].null_count() == 0, c
    # dtypes (Task 20 review M4): dollars are float64, codes int64
    for c in ("amount", "referral_bonus", "product_price"):
        assert ds.events[c].dtype == pl.Float64, c
    for c in ("user_age_bucket", "user_segment", "user_state", "device_os", "device_model",
              "product_category", "currency", "event_type", "label"):
        assert ds.events[c].dtype == pl.Int64, c


def test_codes_index_the_declared_category_lists(dirs, ds):
    # a code is the value's index in schema.json's list (Task 20 review M4)
    tables = {t["name"]: t for t in load_schema(dirs[0])["tables"]}

    def values(table, col):
        return next(c["values"] for c in tables[table]["columns"] if c["name"] == col)

    for code, table, col, key in (("device_model", "device", "kind", "device_id"),
                                  ("device_os", "device", "os", "device_id"),
                                  ("user_age_bucket", "user", "age_band", "user_id")):
        ent = pl.read_parquet(dirs[0] / "entities" / table).select(
            pl.col("id").alias(key), pl.col(col).cast(pl.String))
        j = ds.events.select(key, code).join(ent, on=key, how="left")
        assert j.height == ds.events.height and j[col].null_count() == 0, code
        names = values(table, col)
        decoded = pl.Series([names[i] for i in j[code].to_list()], dtype=pl.String)
        assert (decoded == j[col]).all(), code


def test_bad_rate_in_band(ds):
    assert ds.events["label"].null_count() == 0
    assert 0.003 < ds.events["label"].mean() < 0.08


def test_attributes_are_stable(ds):
    txn = ds.events.filter(pl.col("event_type") == 0)
    assert txn["device_os"].null_count() == 0 and txn["user_state"].null_count() == 0
    assert txn.group_by("device_id").agg(pl.col("device_os").n_unique())["device_os"].max() == 1
    chg = txn.sort("event_time").group_by("user_id").agg(
        (pl.col("user_state").diff().fill_null(0) != 0).sum().alias("c"), pl.len().alias("n"))
    assert chg.filter(pl.col("n") > 5).height > 0
    assert chg.filter(pl.col("n") > 5)["c"].mean() < 3


def test_invites_reference_other_users(ds):
    inv = ds.events.filter(pl.col("event_type") == 1)
    assert inv["inviter_id"].null_count() == 0 and inv["user_id"].null_count() == 0
    assert inv.height > 0 and (inv["inviter_id"] != inv["user_id"]).all()
    txn = ds.events.filter(pl.col("event_type") == 0)
    assert txn["inviter_id"].null_count() == txn.height


def test_invites_agree_with_signups(dirs, ds):
    # contract (Task 14): the invite link lives in the user_signed_up.invited_by event column
    su = read_events(dirs[0], ["user_signed_up"])["user_signed_up"].filter(
        pl.col("invited_by").is_not_null()).select("user_id", "invited_by")
    inv = ds.events.filter(pl.col("event_type") == 1).select("user_id", "inviter_id")
    j = inv.join(su, on="user_id", how="inner")
    assert j.height > 0
    assert (j["inviter_id"] == j["invited_by"]).all()


def test_bounty_hunter_signature_is_planted(ds):
    g = ds.golden.join(ds.events.select("event_id", "event_type"), on="event_id")
    inv = g.filter(pl.col("event_type") == 1)
    assert inv["invitee_is_zombie"].null_count() == 0
    z, n = inv.filter(pl.col("invitee_is_zombie") == 1), inv.filter(pl.col("invitee_is_zombie") == 0)
    assert z.height > 0 and n.height > 0
    assert z["inv_bonus_count_30d"].mean() > 2 * n["inv_bonus_count_30d"].mean()
    # zombies are labeled (their invite row too), and only invite rows carry the flag
    lab = ds.events.select("event_id", "label").join(z.select("event_id"), on="event_id")
    assert (lab["label"] == 1).all()
    assert g.filter(pl.col("event_type") == 0)["invitee_is_zombie"].sum() == 0


def test_rolling_features_have_no_future_leakage(ds):
    first = ds.events.filter(pl.col("event_type") == 0).sort("event_time").group_by(
        "user_id").first()
    g = ds.golden.filter(pl.col("event_id").is_in(first["event_id"].implode()))
    assert g.height == first.height > 0
    assert (g["u_amt_count_30d"] == 0).all()


def test_golden_rows_align_with_events(ds):
    assert ds.golden["event_id"].equals(ds.events["event_id"])
    assert ds.golden.null_count().sum_horizontal().item() == 0


def test_bench_consumes_the_export(dirs):
    events, meta = load_events(dirs[1])
    assert meta["_allowlist"] == resolve_allowlist(meta, events)
    feats = build_features(events, meta["_allowlist"])
    assert feats.height == events.height
    rows = run(dirs[1])
    aucs = [r["auc"] for r in rows if r["model"] == "xgb_raw" and r["split"] == "test"]
    assert aucs and np.isfinite(aucs[0]) and aucs[0] > 0.5
