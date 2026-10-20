"""Legacy fraud dataset (what `bench` reads) from an e-commerce + bounty_hunters run.

Rows: `order_placed` → `event_type` 0; `referral_bonus_paid` → `event_type` 1 with `user_id` =
the invitee and `inviter_id` = the paid inviter. Amounts are dollars. Attributes are integer
codes; `user_state` is the user's region as of the event. `label` = 1 when the row's user (or,
for invite rows, its inviter) is a labeled hunter or zombie. Golden features are strictly-past
rolling aggregates. Every step is a sort, join or rolling window: O(n log n) in rows.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from neorisk_simkit.engine.output import Output
from neorisk_simkit.export import Dataset
from neorisk_simkit.features import rolling, rolling_asof
from neorisk_simkit.io.read import RunData, read

WINDOWS = [7, 14, 30]
ROLES = ["hunter", "zombie"]
EVENT_COLUMNS = (
    "event_id", "event_time", "event_type", "user_id", "device_id", "product_id", "inviter_id",
    "amount", "currency", "referral_bonus", "user_age_bucket", "user_segment", "user_state",
    "device_os", "device_model", "product_category", "product_price", "label")


def _codes(df: pl.DataFrame) -> pl.DataFrame:
    """Categorical columns as integer codes, in declaration order."""
    return df.with_columns(pl.col(pl.Enum).to_physical().cast(pl.Int64))


def tables(run: str | Path | RunData | Output) -> dict[str, pl.DataFrame]:
    """Event and entity tables by name (categoricals as codes), plus `labels` by user_id."""
    if isinstance(run, (str, Path)):
        run = read(run)
    t = {k: _codes(v) for k, v in {**run.events, **run.entities}.items()}
    t["labels"] = run.labels.select(pl.col("target_id").alias("user_id"), "role")
    return t


def _rows(t: dict[str, pl.DataFrame]) -> pl.DataFrame:
    orders = t["order_placed"].select(
        pl.format("order_placed:{}", "event_id").alias("event_id"), "event_time",
        pl.lit(0, pl.Int64).alias("event_type"), "user_id", "device_id",
        pl.col("sku_id").alias("product_id"), pl.lit(None, pl.Int64).alias("inviter_id"),
        (pl.col("amount") / 100.0).alias("amount"), pl.lit(0, pl.Int64).alias("currency"),
        pl.lit(None, pl.Float64).alias("referral_bonus"))
    signup_dev = t["user_signed_up"].select(pl.col("user_id").alias("invitee_id"), "device_id")
    invites = (t["referral_bonus_paid"].join(signup_dev, on="invitee_id", how="left")
               .select(pl.format("referral_bonus_paid:{}", "event_id").alias("event_id"),
                       "event_time", pl.lit(1, pl.Int64).alias("event_type"),
                       pl.col("invitee_id").alias("user_id"), "device_id",
                       pl.lit(None, pl.Int64).alias("product_id"),
                       pl.col("user_id").alias("inviter_id"),
                       pl.lit(None, pl.Float64).alias("amount"),
                       pl.lit(None, pl.Int64).alias("currency"),
                       (pl.col("amount") / 100.0).alias("referral_bonus")))
    return pl.concat([orders, invites]).sort("event_time", "event_id")


def _attributes(rows: pl.DataFrame, t: dict[str, pl.DataFrame]) -> pl.DataFrame:
    users = t["users"].select("user_id", pl.col("age_band").alias("user_age_bucket"),
                              pl.col("acquisition").alias("user_segment"),
                              pl.col("region").alias("_region0"))
    devices = t["devices"].select("device_id", pl.col("os").alias("device_os"),
                                  pl.col("kind").alias("device_model"))
    skus = t["skus"].select(pl.col("sku_id").alias("product_id"),
                            pl.col("category").alias("product_category"),
                            (pl.col("price") / 100.0).alias("product_price"))
    out = (rows.join(users, on="user_id", how="left", maintain_order="left")
           .join(devices, on="device_id", how="left", maintain_order="left")
           .join(skus, on="product_id", how="left", maintain_order="left"))
    moves = t.get("address_changed")
    if moves is not None and moves.height:
        mv = moves.select("user_id", "event_time", pl.col("region").alias("_moved")).sort(
            "event_time")
        out = (out.sort("event_time")
               .join_asof(mv, on="event_time", by="user_id", strategy="backward",
                          allow_exact_matches=False, check_sortedness=False)
               .sort("event_time", "event_id"))
    else:
        out = out.with_columns(pl.lit(None, pl.Int64).alias("_moved"))
    return out.with_columns(pl.coalesce("_moved", "_region0").alias("user_state")).drop(
        "_moved", "_region0")


def _asof(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    return left.join_asof(right, on="event_time", by="user_id", strategy="backward",
                          check_sortedness=False)


def _golden(events: pl.DataFrame) -> pl.DataFrame:
    txn = events.filter(pl.col("event_type") == 0)
    inv = events.filter(pl.col("event_type") == 1)
    vel = rolling(txn, key="user_id", value="amount", windows_days=WINDOWS,
                  aggs=["count", "sum", "mean", "max", "min"], prefix="u_amt")
    devu = rolling(txn, key="device_id", value="user_id", windows_days=[7], aggs=["n_unique"],
                   prefix="dev_users")
    g_bonus = rolling(inv, key="inviter_id", value="referral_bonus", windows_days=WINDOWS,
                      aggs=["count", "sum", "mean", "max"], prefix="inv_bonus")
    inv_feats = (inv.select("event_id", "user_id", "event_time")
                 .join(g_bonus, on="event_id", how="left").drop("event_id").sort("event_time"))
    graph = (events.select("event_id", "user_id", "event_time").sort("event_time")
             .pipe(_asof, inv_feats).drop("user_id", "event_time"))
    invr = rolling_asof(events, inv, query_key="user_id", source_key="inviter_id",
                        value="referral_bonus", windows_days=WINDOWS,
                        aggs=["count", "sum", "mean", "max"], prefix="invr_bonus")
    keep = ("event_id", "amount", "invitee_is_zombie", "actor_role", "label")
    out = (events.select(*keep)
           .join(vel, on="event_id", how="left", maintain_order="left")
           .join(devu, on="event_id", how="left", maintain_order="left")
           .join(graph, on="event_id", how="left", maintain_order="left")
           .join(invr, on="event_id", how="left", maintain_order="left")
           .with_columns(amt_ratio_30d=pl.col("amount").fill_null(0.0)
                         / (pl.col("u_amt_mean_30d") + 1.0))
           .with_columns(pl.exclude(*keep).fill_null(0)))
    feats = [*vel.columns[1:], *devu.columns[1:], *g_bonus.columns[1:], *invr.columns[1:]]
    return out.select("event_id", *feats, "amt_ratio_30d", "invitee_is_zombie", "actor_role",
                      pl.col("label").cast(pl.Float64).alias("score"))


def legacy_fraud(run: str | Path | RunData | Output, meta: dict | None = None) -> Dataset:
    t = tables(run)
    rows = _attributes(_rows(t), t)
    lab = t["labels"].select(
        "user_id", (pl.col("role").replace_strict(ROLES, list(range(1, len(ROLES) + 1)),
                                                  return_dtype=pl.Int64)).alias("actor_role"),
        (pl.col("role") == "zombie").alias("_zombie"))
    labeled = lab["user_id"].implode()
    rows = (rows.join(lab, on="user_id", how="left", maintain_order="left")
            .with_columns(
                label=(pl.col("user_id").is_in(labeled)
                       | ((pl.col("event_type") == 1) & pl.col("inviter_id").is_in(labeled))
                       ).cast(pl.Int64),
                actor_role=pl.col("actor_role").fill_null(0),
                invitee_is_zombie=((pl.col("event_type") == 1)
                                   & pl.col("_zombie").fill_null(False)).cast(pl.Int64)))
    golden = _golden(rows)
    events = rows.select(EVENT_COLUMNS)
    meta = {"scenario": "ecommerce+bounty_hunters", **(meta or {}),
            "feature_allowlist": [c for c, dt in events.schema.items()
                                  if dt.is_numeric() and c != "label" and not c.endswith("_id")]}
    return Dataset(events, golden, meta)
