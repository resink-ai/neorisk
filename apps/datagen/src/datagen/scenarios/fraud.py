import dataclasses

import numpy as np
import polars as pl
import xgboost

from datagen.config import FraudConfig
from neorisk_simkit import (
    AttrSpec,
    Cardinality,
    Dataset,
    EntitySpec,
    RefSpec,
    Volatility,
    XGBScorer,
    attach_asof,
    build_entities,
    calibrate,
    hubs,
    make_uuids,
    map_ids,
    resolve_reference,
    rolling,
    sample_labels,
    skewed,
)

L, H = Cardinality.LOW, Cardinality.HIGH
S, SL, F = Volatility.STATIC, Volatility.SLOW, Volatility.FAST

USER_ATTRS = (
    AttrSpec("age_bucket", L, S, k=10),
    AttrSpec("currency", L, S, k=5),
    AttrSpec("state", L, SL, k=50),
    AttrSpec("street", H, SL),
    AttrSpec("zip", H, SL),
    AttrSpec("segment", L, SL, k=8),
)
DEVICE_ATTRS = (
    AttrSpec("os", L, S, k=4),
    AttrSpec("model", L, S, k=30),
    AttrSpec("battery", L, F, k=10),
    AttrSpec("ip", H, F),
    AttrSpec("user_agent", L, SL, k=20),
)
PRODUCT_ATTRS = (
    AttrSpec("category", L, S, k=20),
    AttrSpec("launch_day", H, S, k=3650),
)

# Planted signal: weight of each golden feature in the label-generating scorer.
GOLDEN_WEIGHTS = {
    "amt_ratio_30d": 1.0,
    "u_amt_count_7d": 0.3,
    "u_amt_max_30d": 0.4,
    "dev_users_n_unique_7d": 0.8,
    "addr_chg_sum_30d": 0.5,
    "inv_bonus_count_30d": 0.8,
    "inv_bonus_sum_30d": 1.0,
    "inv_zombie_mean_30d": 1.2,
}

T0 = np.datetime64("2026-01-01T00:00:00", "us")


def _times(rng, lo: np.datetime64, hi: np.datetime64, n: int) -> np.ndarray:
    span = int((hi - lo) / np.timedelta64(1, "us"))
    offs = (rng.random(n) * span).astype("int64")
    return np.sort(lo + offs.astype("timedelta64[us]"))


def _invites(cfg, users, created, user_device, rng):
    """Invite events + the hidden zombie flag. Mutates ``user_device`` for ring members."""
    n_u = cfg.n_users
    hunter_idx = np.arange(cfg.n_hunters)
    is_invited = (rng.random(n_u) < cfg.invite_frac) & (np.arange(n_u) >= cfg.n_hunters)
    invitee = np.flatnonzero(is_invited)
    ref = RefSpec("inviter_idx", "user", hubs(hunter_idx, cfg.hunter_prob))
    inviter = resolve_reference(ref, created[invitee], created, rng)
    inviter_np = inviter.fill_null(-1).to_numpy()
    from_hunter = np.isin(inviter_np, hunter_idx)
    zombie = rng.random(len(invitee)) < np.where(from_hunter, 0.9, 0.02)
    bonus = np.where(
        from_hunter, rng.integers(30, 100, len(invitee)), rng.integers(1, 10, len(invitee))
    )
    ring = zombie & from_hunter & (rng.random(len(invitee)) < 0.7)
    user_device[invitee[ring]] = user_device[inviter_np[ring]]  # multi-account device sharing
    user_is_zombie = np.zeros(n_u, dtype=bool)
    user_is_zombie[invitee] = zombie
    df = pl.DataFrame(
        {
            "event_time": created[invitee],
            "event_type": np.ones(len(invitee), dtype="int64"),
            "user_idx": invitee.astype("int64"),
            "device_idx": user_device[invitee].astype("int64"),
            "inviter_idx": inviter_np.astype("int64"),
            "referral_bonus": bonus.astype("int64"),
            "zombie": zombie,
        }
    ).with_columns(
        pl.when(pl.col("inviter_idx") >= 0).then(pl.col("inviter_idx")).alias("inviter_idx")
    )
    return df, user_is_zombie


def _transactions(cfg, n_txn, created, user_device, user_is_zombie, t1, rng):
    times = _times(rng, created[0], t1, n_txn)
    m = np.searchsorted(created, times, side="right")
    choose = skewed(2.0)
    user = choose(m, rng)
    for _ in range(3):  # zombies are (almost) inactive
        bad = user_is_zombie[user]
        if not bad.any():
            break
        user[bad] = choose(m[bad], rng)
    device = np.where(
        rng.random(n_txn) < 0.1, rng.integers(0, cfg.n_devices, n_txn), user_device[user]
    )
    product = np.where(rng.random(n_txn) < 0.7, rng.integers(0, cfg.n_products, n_txn), -1)
    cashout = (rng.random(cfg.n_users) < 0.03) & ~user_is_zombie
    df = pl.DataFrame(
        {
            "event_time": times,
            "event_type": np.zeros(n_txn, dtype="int64"),
            "user_idx": user.astype("int64"),
            "device_idx": device.astype("int64"),
            "product_idx": product.astype("int64"),
            "amount": np.round(rng.lognormal(3.0, 0.8, n_txn), 2),
            "cashout_user": cashout[user],
        }
    ).with_columns(
        pl.when(pl.col("product_idx") >= 0).then(pl.col("product_idx")).alias("product_idx")
    )
    # warm-up / cash-out: cashout users send small amounts, then a large burst at the end
    return (
        df.with_columns(rank=pl.int_range(pl.len()).over("user_idx"), n=pl.len().over("user_idx"))
        .with_columns(
            amount=pl.when(pl.col("cashout_user"))
            .then(
                pl.when(pl.col("rank") >= (pl.col("n") * 0.9).floor())
                .then(pl.col("amount") * 15)
                .otherwise(pl.col("amount") * 0.3)
            )
            .otherwise(pl.col("amount"))
        )
        .drop("rank", "n", "cashout_user")
    )


def _address_changes(events: pl.DataFrame, users) -> pl.DataFrame:
    ch = (
        users.attrs.filter(pl.col("attr") == "state")
        .join(users.ids.select("idx", "created_at"), on="idx")
        .filter(pl.col("valid_from") > pl.col("created_at"))
        .select(
            pl.lit(None, dtype=pl.Utf8).alias("event_id"),
            pl.col("idx").alias("user_idx"),
            pl.col("valid_from").alias("event_time"),
            pl.lit(1.0).alias("is_change"),
        )
    )
    ev = events.select("event_id", "user_idx", "event_time").with_columns(is_change=pl.lit(0.0))
    both = pl.concat([ev, ch.select(ev.columns)]).with_row_index("_rid")
    r = rolling(
        both,
        key="user_idx",
        value="is_change",
        windows_days=[30],
        aggs=["sum"],
        prefix="addr_chg",
        id_col="_rid",
    )
    return (
        both.join(r, on="_rid")
        .filter(pl.col("event_id").is_not_null())
        .select("event_id", "addr_chg_sum_30d")
    )


def _golden(events: pl.DataFrame, users) -> pl.DataFrame:
    txn = events.filter(pl.col("event_type") == 0)
    inv = events.filter(pl.col("event_type") == 1).with_columns(
        zombie_f=pl.col("zombie").cast(pl.Float64)
    )
    vel = rolling(
        txn,
        key="user_idx",
        value="amount",
        windows_days=[7, 14, 30],
        aggs=["count", "sum", "mean", "max", "min"],
        prefix="u_amt",
    )
    devu = rolling(
        txn,
        key="device_idx",
        value="user_idx",
        windows_days=[7],
        aggs=["n_unique"],
        prefix="dev_users",
    )
    g_bonus = rolling(
        inv,
        key="inviter_idx",
        value="referral_bonus",
        windows_days=[7, 14, 30],
        aggs=["count", "sum", "mean", "max"],
        prefix="inv_bonus",
    )
    g_zombie = rolling(
        inv,
        key="inviter_idx",
        value="zombie_f",
        windows_days=[30],
        aggs=["mean"],
        prefix="inv_zombie",
    )
    # graph features of the invite that brought each user in, looked up as-of event time
    # join_asof cannot take null `by` keys: drop them on both sides; the left join in `out`
    # restores the dropped events (their graph features then fill to 0).
    inv_feats = (
        inv.filter(pl.col("user_idx").is_not_null())
        .select("event_id", "user_idx", "event_time")
        .join(g_bonus, on="event_id", how="left")
        .join(g_zombie, on="event_id", how="left")
        .drop("event_id")
        .sort("event_time")
    )
    graph = (
        events.select("event_id", "user_idx", "event_time")
        .filter(pl.col("user_idx").is_not_null())
        .sort("event_time")
        .join_asof(
            inv_feats, on="event_time", by="user_idx", strategy="backward", check_sortedness=False
        )
        .drop("user_idx", "event_time")
    )
    zombie_flag = events.select(
        "event_id", pl.col("zombie").fill_null(False).cast(pl.Int64).alias("invitee_is_zombie")
    )
    out = (
        events.select("event_id", "amount")
        .join(vel, on="event_id", how="left", maintain_order="left")
        .join(devu, on="event_id", how="left", maintain_order="left")
        .join(_address_changes(events, users), on="event_id", how="left", maintain_order="left")
        .join(graph, on="event_id", how="left", maintain_order="left")
        .join(zombie_flag, on="event_id", how="left", maintain_order="left")
        .with_columns(
            amt_ratio_30d=pl.col("amount").fill_null(0.0) / (pl.col("u_amt_mean_30d") + 1.0)
        )
        .drop("amount")
    )
    return out.with_columns(pl.exclude("event_id").fill_null(0))


def generate(cfg: FraudConfig) -> Dataset:
    cfg.validate()
    rng = np.random.default_rng(cfg.seed)
    t0, t1 = T0, T0 + np.timedelta64(cfg.span_days, "D")

    users = build_entities(EntitySpec("user", cfg.n_users, USER_ATTRS, 0.5), t0, t1, rng)
    devices = build_entities(EntitySpec("device", cfg.n_devices, DEVICE_ATTRS, 0.0), t0, t1, rng)
    products = build_entities(
        EntitySpec("product", cfg.n_products, PRODUCT_ATTRS, 0.0), t0, t1, rng
    )
    created = users.created_at()
    user_device = rng.integers(0, cfg.n_devices, cfg.n_users)

    invites, user_is_zombie = _invites(cfg, users, created, user_device, rng)
    n_txn = cfg.n_events - invites.height
    if n_txn <= 0:
        raise ValueError("n_events is too small for the configured invite_frac")
    txns = _transactions(cfg, n_txn, created, user_device, user_is_zombie, t1, rng)

    events = (
        pl.concat([invites, txns], how="diagonal_relaxed")
        .sort("event_time", "event_type", "user_idx", maintain_order=True)
        .with_columns(event_id=pl.Series(make_uuids(cfg.n_events, rng)))
    )
    events = attach_asof(events, users, idx_col="user_idx")
    events = attach_asof(events, devices, idx_col="device_idx")
    events = attach_asof(events, products, idx_col="product_idx")
    home = events["user_currency"].to_numpy()
    other = rng.integers(0, 5, events.height)
    events = events.with_columns(
        currency=pl.when(pl.col("event_type") == 0).then(
            pl.Series(np.where(rng.random(events.height) < 0.9, home, other))
        )
    )

    golden = _golden(events, users)
    # labels are attached to events by position, so golden rows must be in events' order
    if not golden["event_id"].equals(events["event_id"]):
        raise RuntimeError("golden rows are not aligned with events; labels would be scrambled")
    p = calibrate(XGBScorer(GOLDEN_WEIGHTS, seed=cfg.seed).score(golden), cfg.target_bad_rate)
    labels = sample_labels(p, rng)
    golden = golden.with_columns(score=pl.Series(p))

    out = events.with_columns(
        user_id=map_ids(users, events["user_idx"]),
        device_id=map_ids(devices, events["device_idx"]),
        product_id=map_ids(products, events["product_idx"]),
        inviter_id=map_ids(users, events["inviter_idx"]),
        label=pl.Series(labels),
    ).drop("user_idx", "device_idx", "product_idx", "inviter_idx", "zombie")
    lead = [
        "event_id",
        "event_time",
        "event_type",
        "user_id",
        "device_id",
        "product_id",
        "inviter_id",
        "amount",
        "currency",
        "referral_bonus",
    ]
    out = out.select(lead + [c for c in out.columns if c not in lead and c != "label"] + ["label"])

    meta = {
        "scenario": "fraud",
        "seed": cfg.seed,
        "config": dataclasses.asdict(cfg),
        "versions": {"polars": pl.__version__, "xgboost": xgboost.__version__},
    }
    return Dataset(out, golden, meta)
