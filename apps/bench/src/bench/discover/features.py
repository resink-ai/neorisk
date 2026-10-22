"""One behaviour vector per user, computed from the world alone (no labels)."""

from __future__ import annotations

import numpy as np
import polars as pl

from bench.discover.world import World

NAMES = ["orders", "near_min_share", "cheapest_share", "views_per_order", "sessions",
         "devices", "max_device_users", "invited", "invites_sent", "bonuses",
         "hours_to_first_order"]
NEAR_MIN_CENTS = 500          # an order within this much above the minimum is "sized to qualify"
_CACHE: dict[int, tuple[np.ndarray, list[str]]] = {}


def cheapest_qualifying_sku(world: World) -> int:
    ok = world.skus.filter(pl.col("price") >= world.min_order_cents)
    return int(ok.sort("price", "sku_id")["sku_id"][0])


def user_devices(world: World) -> pl.DataFrame:
    """Distinct (user_id, device_id) pairs seen in sessions, sign-ups and device ownership."""
    return pl.concat([world.sessions.select("user_id", "device_id"),
                      world.signups.select("user_id", "device_id"),
                      world.devices.select("user_id", "device_id")]).drop_nulls().unique()


def _join(base: pl.DataFrame, df: pl.DataFrame) -> pl.DataFrame:
    return base.join(df, on="user_id", how="left")


def user_matrix(world: World) -> tuple[np.ndarray, list[str]]:
    key = id(world)
    if key in _CACHE:
        return _CACHE[key]
    cheap = cheapest_qualifying_sku(world)
    lo = world.min_order_cents
    u = world.users.select("user_id", "created_at", (pl.col("acquisition") == "invite")
                           .cast(pl.Float64).alias("invited"))
    o = world.orders.group_by("user_id").agg(
        pl.len().alias("orders"),
        ((pl.col("amount") >= lo) & (pl.col("amount") < lo + NEAR_MIN_CENTS)).mean()
        .alias("near_min_share"),
        (pl.col("sku_id") == cheap).mean().alias("cheapest_share"),
        pl.col("created_at").min().alias("first_order"))
    v = world.views.group_by("user_id").agg(pl.len().alias("views"))
    s = world.sessions.group_by("user_id").agg(pl.len().alias("sessions"))
    ud = user_devices(world)
    dev_users = ud.group_by("device_id").agg(pl.len().alias("n"))
    d = ud.join(dev_users, on="device_id").group_by("user_id").agg(
        pl.len().alias("devices"), pl.col("n").max().alias("max_device_users"))
    inv = world.users.drop_nulls("invited_by").group_by("invited_by").agg(
        pl.len().alias("invites_sent")).rename({"invited_by": "user_id"})
    b = world.bonuses.group_by("user_id").agg(pl.len().alias("bonuses"))
    t = u
    for df in (o, v, s, d, inv, b):
        t = _join(t, df)
    horizon = (world.users["created_at"].max() - world.users["created_at"].min()
               ).total_seconds() / 3600
    t = t.with_columns(
        pl.col("orders", "views", "sessions", "invites_sent", "bonuses").fill_null(0)
        .cast(pl.Float64),
        pl.col("near_min_share", "cheapest_share").fill_null(0.0),
        pl.col("devices", "max_device_users").fill_null(1).cast(pl.Float64),
        ((pl.col("first_order") - pl.col("created_at")).dt.total_seconds() / 3600)
        .fill_null(horizon).clip(0, None).alias("hours_to_first_order"))
    t = t.with_columns((pl.col("views") / pl.col("orders").clip(1, None)).alias("views_per_order"))
    x = t.select(NAMES).to_numpy().astype(float)
    _CACHE[key] = (x, list(NAMES))
    return _CACHE[key]


def standardize(x: np.ndarray) -> np.ndarray:
    z = np.log1p(np.clip(x, 0, None))
    sd = z.std(axis=0)
    return (z - z.mean(axis=0)) / np.where(sd > 0, sd, 1.0)
