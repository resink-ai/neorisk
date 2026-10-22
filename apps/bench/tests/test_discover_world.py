"""The world view hides who is in the ring; the truth keeps it, aligned to the same users."""

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

pytest_plugins = ["discover_fixture"]

PROVENANCE = {"partition_id", "action_id", "cause_id", "seq", "event_id"}


def test_truth_counts_the_ring_and_its_stealth_members(discover_run, world_truth):
    world, truth = world_truth
    lab = pl.read_parquet(discover_run / "labels" / "labels.parquet")
    lab = lab.filter(pl.col("target_table") == "users")
    assert truth.bad.sum() == lab.height > 30
    assert truth.stealth.sum() == (lab["variant"] == "stealth").sum() > 0
    assert not (truth.stealth & ~truth.bad).any()
    assert len(truth.bad) == len(world.user_ids) == world.users.height
    assert set(np.unique(truth.cohort)) == {"base", "promoter", "promoted_friend", "ring"}
    assert (truth.cohort[truth.bad] == "ring").all()
    assert not np.isnat(truth.available_at[truth.bad]).any()


def test_world_has_no_provenance_columns(world_truth):
    world, _ = world_truth
    for name, df in world.tables().items():
        assert not PROVENANCE & set(df.columns), name


def test_world_ids_are_consistent_across_tables(world_truth):
    world, _ = world_truth
    ids = set(world.user_ids.tolist())
    for name, df in world.tables().items():
        for col in ("user_id", "invited_by", "invitee_id"):
            if col in df.columns:
                assert set(df[col].drop_nulls()) <= ids, (name, col)
    assert set(world.sessions["device_id"]) <= set(world.devices["device_id"])


def _per_user(world, df, col, how):
    agg = df.group_by("user_id").agg(getattr(pl.col(col), how)().alias("v"))
    v = world.users.select("user_id").join(agg, on="user_id", how="left")["v"]
    return v.fill_null(v.median()).cast(pl.Float64).to_numpy()


def test_no_id_or_time_column_scores_ring_auc_above_0_8(world_truth):
    world, truth = world_truth
    cols = {
        "user_id": world.users["user_id"].cast(pl.Float64).to_numpy(),
        "min device_id": _per_user(world, world.devices, "device_id", "min"),
        "min session_id": _per_user(world, world.sessions, "session_id", "min"),
        "min order_id": _per_user(world, world.orders, "order_id", "min"),
        "row order": np.arange(world.users.height, dtype=float),
    }
    for name, v in cols.items():
        auc = roc_auc_score(truth.bad, v)
        assert max(auc, 1 - auc) < 0.8, (name, auc)
