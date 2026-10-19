"""Legacy adapter (D87): a run of the e-commerce pack (with the bounty_hunters overlay) in the
shape of today's fraud dataset, which `bench` reads: `events.parquet`, `golden.parquet` and
`meta.json` (written by `neorisk_simkit.export.export`).

Mapping
- `order_placed` → `event_type` 0; the inviter's `referral_bonus_paid` (`role = "inviter"`) →
  `event_type` 1 with `user_id` = the invitee (its `invitee_id` column) and `inviter_id` = the
  inviter (its `user_id` column). Both are event columns, never `entities/user.invited_by`, which
  holds a draw for users who were not referred (Task 14 contract). An invitee's `user_signed_up`
  names the same inviter (`invited_by`).
- `event_id` = `"<event type>:<engine event_id>"`; rows in canonical order
  `(event_time, lamport, partition_id, seq)`; `event_time` naive UTC microseconds.
- Amounts in dollars (float64, cents / 100). Categorical attributes are integer codes: the
  value's index in its declared category list (`schema/schema.json`).
- User attributes: `user_age_bucket` = `age_band`; `user_segment` = acquisition channel (the
  user's `user_signed_up.acquisition` when that signup was exported, else the entity value);
  `user_state` = `region` as of the event time (the last `history/address` change at or before
  it, else the creation value of `entities/user`). Device: `device_os` = `os`,
  `device_model` = `kind`. Product (orders only): `product_category`, `product_price`.
- An invite row's device is the invitee's signup device, else its latest session or order
  device at or before the invite, else its first one after (when that activity was warm-up).
- `label` = 1 when the row's user (or, for invite rows, its inviter) is a cohort target whose
  last `labels/labels_*` row has `final_label`; label maturity is ignored (M4).

Golden features mirror `datagen.scenarios.fraud._golden` (names and windows), computed from the
adapter's events with `features.rolling` / `rolling_asof` over strictly earlier rows, plus
`invitee_is_zombie`, `actor_role` (0 none, else 1 + the role's index in its labels table) and
`score` = label.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from neorisk_simkit.export import Dataset
from neorisk_simkit.features import rolling, rolling_asof
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.schema.schema_json import load_schema

ORDER, INVITE = "order_placed", "referral_bonus_paid"
KEY = ("event_time", "lamport", "partition_id", "seq")       # canonical order
WINDOWS = [7, 14, 30]
EVENT_COLUMNS = (
    "event_id", "event_time", "event_type", "user_id", "device_id", "product_id", "inviter_id",
    "amount", "currency", "referral_bonus", "user_age_bucket", "user_segment", "user_state",
    "device_os", "device_model", "product_category", "product_price", "label")


class _Schema:
    def __init__(self, doc: dict[str, Any]):
        self.tables = {t["name"]: t for t in doc["tables"]}

    def values(self, table: str, col: str) -> list[str]:
        for c in self.tables[table]["columns"]:
            if c["name"] == col:
                return list(c["values"])
        raise KeyError(f"{table}.{col}")

    def code(self, table: str, col: str, expr: pl.Expr | None = None) -> pl.Expr:
        """`col` of `table` as the index of its value in the declared category list."""
        vals = self.values(table, col)
        return (pl.col(col) if expr is None else expr).cast(pl.String).replace_strict(
            vals, list(range(len(vals))), return_dtype=pl.Int64)

    def label_tables(self) -> list[str]:
        return [n for n, t in self.tables.items() if t["kind"] == "label"]


def _entities(run_dir: Path, table: str) -> pl.DataFrame:
    return pl.read_parquet(run_dir / "entities" / table)


def _parts(folder: Path) -> pl.DataFrame | None:
    files = sorted(folder.rglob("*.parquet"))
    return pl.read_parquet(files) if files else None


def _naive(df: pl.DataFrame, col: str = "event_time") -> pl.DataFrame:
    return df.with_columns(pl.col(col).dt.replace_time_zone(None))


def _raw_rows(ev: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Orders and inviter bonus rows, unified and in canonical order (engine ids kept)."""
    usd = pl.col("amount").cast(pl.Float64) / 100.0
    orders = ev[ORDER].select(
        pl.format(f"{ORDER}:{{}}", "event_id").alias("event_id"), *KEY,
        pl.lit(0, pl.Int64).alias("event_type"), "user_id", "device_id",
        pl.col("sku_id").alias("product_id"), pl.lit(None, pl.Int64).alias("inviter_id"),
        usd.alias("amount"), pl.lit(0, pl.Int64).alias("currency"),
        pl.lit(None, pl.Float64).alias("referral_bonus"))
    invites = ev[INVITE].filter(pl.col("role").cast(pl.String) == "inviter").select(
        pl.format(f"{INVITE}:{{}}", "event_id").alias("event_id"), *KEY,
        pl.lit(1, pl.Int64).alias("event_type"), pl.col("invitee_id").alias("user_id"),
        pl.lit(None, pl.Int64).alias("device_id"), pl.lit(None, pl.Int64).alias("product_id"),
        pl.col("user_id").alias("inviter_id"), pl.lit(None, pl.Float64).alias("amount"),
        pl.lit(None, pl.Int64).alias("currency"), usd.alias("referral_bonus"))
    return _naive(pl.concat([orders, invites]).sort(list(KEY), maintain_order=True))


def _asof(left: pl.DataFrame, right: pl.DataFrame, strategy: str) -> pl.DataFrame:
    # both sides are sorted by event_time here; polars cannot verify that within `by` groups
    return left.join_asof(right, on="event_time", by="user_id", strategy=strategy,
                          check_sortedness=False)


def _invite_devices(rows: pl.DataFrame, ev: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Fill an invite row's device: the invitee's signup device; else the device of its latest
    session or order at or before the invite; else (that activity fell in the warm-up, which is
    not exported) its first session or order device after it."""
    by_signup = ev["user_signed_up"].select("user_id", pl.col("device_id").alias("_su"))
    seen = _naive(pl.concat([ev[n].select("event_time", "user_id", "device_id")
                             for n in ("session_started", ORDER)])).sort("event_time")
    return (_asof(_asof(rows.join(by_signup, on="user_id", how="left", maintain_order="left"),
                        seen.rename({"device_id": "_before"}), "backward"),
                  seen.rename({"device_id": "_after"}), "forward")
            .with_columns(pl.when(pl.col("event_type") == 1)
                          .then(pl.coalesce("_su", "_before", "_after"))
                          .otherwise(pl.col("device_id")).alias("device_id"))
            .drop("_su", "_before", "_after"))


def _attributes(run_dir: Path, sc: _Schema, rows: pl.DataFrame,
                signups: pl.DataFrame) -> pl.DataFrame:
    users = _entities(run_dir, "user").select(
        pl.col("id").alias("user_id"),
        sc.code("user", "age_band").alias("user_age_bucket"),
        sc.code("user", "acquisition").alias("_seg_entity"),
        sc.code("user", "region").alias("_state0"))
    seg = signups.select("user_id", sc.code("user_signed_up", "acquisition").alias("_seg_su"))
    devices = _entities(run_dir, "device").select(
        pl.col("id").alias("device_id"), sc.code("device", "os").alias("device_os"),
        sc.code("device", "kind").alias("device_model"))
    skus = _entities(run_dir, "sku").select(
        pl.col("id").alias("product_id"), sc.code("sku", "category").alias("product_category"),
        (pl.col("price").cast(pl.Float64) / 100.0).alias("product_price"))
    out = (rows.join(users, on="user_id", how="left", maintain_order="left")
           .join(seg, on="user_id", how="left", maintain_order="left")
           .join(devices, on="device_id", how="left", maintain_order="left")
           .join(skus, on="product_id", how="left", maintain_order="left"))
    hist = _parts(run_dir / "history" / "address")
    if hist is not None and hist.height:
        moves = _naive(hist.rename({"valid_from": "event_time"})).sort(
            ["event_time", "lamport", "partition_id", "seq"]).select(
            pl.col("entity_id").alias("user_id"), "event_time",
            sc.code("address", "region").alias("_state"))
        out = _asof(out, moves, "backward")
    else:
        out = out.with_columns(pl.lit(None, pl.Int64).alias("_state"))
    return out.with_columns(
        pl.coalesce("_seg_su", "_seg_entity").alias("user_segment"),
        pl.coalesce("_state", "_state0").alias("user_state"),
    ).drop("_seg_su", "_seg_entity", "_state", "_state0")


def _targets(run_dir: Path, sc: _Schema) -> pl.DataFrame:
    """One row per cohort target: its last label row's `final_label` and role code
    (1 + the role's index in its labels table)."""
    frames = []
    for name in sc.label_tables():
        df = _parts(run_dir / "labels" / name)
        if df is None or df.height == 0:
            continue
        frames.append(df.sort(list(KEY), maintain_order=True).select(
            "target_id", *KEY, pl.col("final_label").fill_null(False).alias("final_label"),
            (sc.code(name, "role") + 1).alias("actor_role"),
            (pl.col("role").cast(pl.String) == "zombie").alias("zombie")))
    if not frames:
        return pl.DataFrame(schema={"target_id": pl.Int64, "final_label": pl.Boolean,
                                    "actor_role": pl.Int64, "zombie": pl.Boolean})
    return (pl.concat(frames).sort(list(KEY), maintain_order=True)
            .group_by("target_id", maintain_order=True).last()
            .select("target_id", "final_label", "actor_role", "zombie"))


def _golden(events: pl.DataFrame) -> pl.DataFrame:
    """Batch rolling features of today's names and windows (`fraud._golden`), strictly past."""
    txn = events.filter(pl.col("event_type") == 0)
    inv = events.filter(pl.col("event_type") == 1)
    vel = rolling(txn, key="user_id", value="amount", windows_days=WINDOWS,
                  aggs=["count", "sum", "mean", "max", "min"], prefix="u_amt")
    devu = rolling(txn, key="device_id", value="user_id", windows_days=[7], aggs=["n_unique"],
                   prefix="dev_users")
    g_bonus = rolling(inv, key="inviter_id", value="referral_bonus", windows_days=WINDOWS,
                      aggs=["count", "sum", "mean", "max"], prefix="inv_bonus")
    # graph features of the invite that brought each user in, looked up as of event time
    inv_feats = (inv.select("event_id", "user_id", "event_time")
                 .join(g_bonus, on="event_id", how="left").drop("event_id").sort("event_time"))
    graph = (events.select("event_id", "user_id", "event_time").sort("event_time")
             .pipe(_asof, inv_feats, "backward")
             .drop("user_id", "event_time"))
    # the event's user *as an inviter*: their own invites in [t-w, t), at every event they make
    invr_bonus = rolling_asof(events, inv, query_key="user_id", source_key="inviter_id",
                              value="referral_bonus", windows_days=WINDOWS,
                              aggs=["count", "sum", "mean", "max"], prefix="invr_bonus")
    out = (events.select("event_id", "amount", "invitee_is_zombie", "actor_role", "label")
           .join(vel, on="event_id", how="left", maintain_order="left")
           .join(devu, on="event_id", how="left", maintain_order="left")
           .join(graph, on="event_id", how="left", maintain_order="left")
           .join(invr_bonus, on="event_id", how="left", maintain_order="left")
           .with_columns(amt_ratio_30d=pl.col("amount").fill_null(0.0)
                         / (pl.col("u_amt_mean_30d") + 1.0))
           .with_columns(pl.exclude("event_id", "amount", "invitee_is_zombie", "actor_role",
                                    "label").fill_null(0)))
    feats = [*vel.columns[1:], *devu.columns[1:], *g_bonus.columns[1:], *invr_bonus.columns[1:]]
    return out.select("event_id", *feats, "amt_ratio_30d", "invitee_is_zombie", "actor_role",
                      pl.col("label").cast(pl.Float64).alias("score"))


def legacy_fraud(run_dir: str | Path) -> Dataset:
    """Today's fraud dataset (events, golden, meta) from the run folder `run_dir` (D87)."""
    d = Path(run_dir)
    manifest = json.loads((d / "manifest.json").read_text())
    sc = _Schema(load_schema(d))
    ev = read_events(d, [ORDER, INVITE, "user_signed_up", "session_started"])
    rows = _attributes(d, sc, _invite_devices(_raw_rows(ev), ev), ev["user_signed_up"])

    t = _targets(d, sc)
    labeled = t.filter(pl.col("final_label"))["target_id"].implode()
    user_t = t.select(pl.col("target_id").alias("user_id"), "actor_role", "zombie")
    rows = (rows.join(user_t, on="user_id", how="left", maintain_order="left")
            .with_columns(
                label=(pl.col("user_id").is_in(labeled)
                       | ((pl.col("event_type") == 1) & pl.col("inviter_id").is_in(labeled))
                       ).cast(pl.Int64),
                actor_role=pl.col("actor_role").fill_null(0),
                invitee_is_zombie=((pl.col("event_type") == 1)
                                   & pl.col("zombie").fill_null(False)).cast(pl.Int64)))
    golden = _golden(rows)
    events = rows.select(EVENT_COLUMNS)
    if not golden["event_id"].equals(events["event_id"]):
        raise RuntimeError("golden rows are not aligned with events")

    overlays = list(manifest.get("overlays") or {})
    run_name = f"{manifest['profile']}-s{manifest['seed']}" + "".join(f"+{o}" for o in overlays)
    meta = {
        "scenario": "+".join([manifest["pack"], *overlays]),
        "seed": manifest["seed"],
        "source": {"pack": manifest["pack"], "revision": manifest["pack_revision"],
                   "overlays": manifest.get("overlays") or {}, "run": run_name},
        # upper bound on raw model inputs (bench D29)
        "feature_allowlist": [c for c, dt in events.schema.items()
                              if dt.is_numeric() and c != "label" and not c.endswith("_id")],
    }
    return Dataset(events, golden, meta)
