"""The two halves of a run: the world a discovery method may look at, and the hidden truth.

The world is the run's behaviour tables with every id passed through a seeded permutation
(`io.public_ids.feistel`) and the provenance columns dropped: overlay ids, `partition_id`,
`action_id` and `cause_id` would name the ring outright. Labels and cases go into `Truth`,
which only the oracle and the scorer read.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import polars as pl

from neorisk_simkit.io.public_ids import _map
from neorisk_simkit.io.read import RunData, read

DROP = ("event_id", "event_type", "seq", "partition_id", "cause_id", "action_id")
# world table -> source table in the run
SOURCES = {"users": "users", "devices": "devices", "skus": "skus", "orders": "orders",
           "sessions": "session_started", "views": "product_viewed", "signups": "user_signed_up",
           "returns": "order_returned", "bonuses": "referral_bonus_paid",
           "addresses": "address_changed"}
EXTRA_SPACES = {"session_id": "session"}          # plain i64 ids minted per partition


@dataclass(frozen=True)
class World:
    users: pl.DataFrame
    devices: pl.DataFrame
    skus: pl.DataFrame
    orders: pl.DataFrame
    sessions: pl.DataFrame
    views: pl.DataFrame
    signups: pl.DataFrame
    returns: pl.DataFrame
    bonuses: pl.DataFrame
    addresses: pl.DataFrame
    user_ids: np.ndarray          # world ids in `users` row order: the index of every score array
    min_order_cents: int = 3000   # the published referral rule: an invitee's qualifying order
    cache: dict = field(default_factory=dict, compare=False, repr=False)   # derived matrices

    def tables(self) -> dict[str, pl.DataFrame]:
        return {f.name: getattr(self, f.name) for f in fields(self)
                if isinstance(getattr(self, f.name), pl.DataFrame)}

    def index(self, ids) -> np.ndarray:
        """Positions in `user_ids` of world user ids (all must exist)."""
        if "order" not in self.cache:
            order = np.argsort(self.user_ids, kind="stable")
            self.cache["order"] = (order, self.user_ids[order])
        order, sorted_ids = self.cache["order"]
        return order[np.searchsorted(sorted_ids, ids)]


@dataclass(frozen=True)
class Truth:
    bad: np.ndarray               # bool, aligned to World.user_ids
    stealth: np.ndarray           # bool
    cohort: np.ndarray            # "base" | "promoter" | "promoted_friend" | "ring"
    available_at: np.ndarray      # datetime64[us]; NaT when not bad


def _public(df: pl.DataFrame, table: dict, seed: int) -> pl.DataFrame:
    cols = []
    for c in table["columns"]:
        name = c["name"]
        if name not in df.columns or name in DROP:
            continue
        if c["type"] == "ref":
            cols.append(_map(df[name], c["ref"], seed))
        elif table["group"] == "entity" and name == table.get("key"):
            cols.append(_map(df[name], table["name"], seed))
        elif name in EXTRA_SPACES:
            cols.append(_map(df[name], EXTRA_SPACES[name], seed))
    df = df.with_columns(cols) if cols else df
    df = df.drop([c for c in DROP if c in df.columns])
    return df.with_columns(pl.col(pl.Enum, pl.Categorical).cast(pl.String))


def _sort(df: pl.DataFrame) -> pl.DataFrame:
    """Rows in time order, ties by public id, so row position says nothing about the run."""
    t = "event_time" if "event_time" in df.columns else "created_at"
    keys = [t] if t in df.columns else []
    return df.sort(keys + [df.columns[0]]) if keys else df.sort(df.columns[0])


def load(run: str | Path | RunData, seed: int) -> tuple[World, Truth]:
    run = read(run) if isinstance(run, (str, Path)) else run
    schema = {t["name"]: t for t in run.schema["tables"]}
    frames = {}
    for name, src in SOURCES.items():
        df = run.entities.get(src)
        if df is None:
            df = run.events[src]
        frames[name] = _sort(_public(df, schema[src], seed))
    users = frames["users"].sort("created_at", "user_id")
    frames["users"] = users
    world = World(**frames, user_ids=users["user_id"].to_numpy(),
                  min_order_cents=int(run.manifest["config"].get("min_order_cents", 3000)))

    # truth, through raw ids, then mapped the same way
    raw_users = run.entities["users"]["user_id"]
    pub = _map(raw_users, "users", seed)
    cohorts = run.cases.select(pl.col("partition_id"), pl.col("cohort"))
    su = run.events["user_signed_up"].select("user_id", "partition_id").join(
        cohorts, on="partition_id", how="left")
    lab = run.labels.filter(pl.col("target_table") == "users").select(
        pl.col("target_id").alias("user_id"), "variant", "label_available_at")
    t = (pl.DataFrame({"user_id": raw_users, "pub": pub})
         .join(su.select("user_id", "cohort"), on="user_id", how="left")
         .join(lab, on="user_id", how="left"))
    t = pl.DataFrame({"pub": world.user_ids}).join(t, on="pub", how="left")
    bad = t["label_available_at"].is_not_null().to_numpy()
    cohort = t["cohort"].fill_null("base").replace(
        {"bounty_hunter": "ring", "zombie": "ring"}).to_numpy().astype(str)
    cohort[bad] = "ring"
    truth = Truth(bad=bad, stealth=(t["variant"] == "stealth").fill_null(False).to_numpy(),
                  cohort=cohort,
                  available_at=t["label_available_at"].dt.replace_time_zone(None)
                  .to_numpy().astype("datetime64[us]"))
    return world, truth
