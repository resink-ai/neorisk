from collections.abc import Sequence

import polars as pl

from neorisk_simkit import rolling, rolling_asof

WINDOWS = (7, 14, 30)
# near-unique ints act like IDs (product_launch_day is a near-unique product proxy)
IDENTIFIER_LIKE = ("user_street", "user_zip", "device_ip", "product_launch_day")
_REQUIRED = (
    "event_id",
    "event_time",
    "event_type",
    "user_id",
    "device_id",
    "inviter_id",
    "amount",
    "referral_bonus",
    "user_state",
)


def feature_names(features: pl.DataFrame) -> list[str]:
    return [c for c in features.columns if c != "event_id"]


def _raw_columns(events: pl.DataFrame, allowlist: Sequence[str] | None = None) -> list[str]:
    skip = {"label", "event_id", "event_time", *IDENTIFIER_LIKE}
    allowed = None if allowlist is None else set(allowlist)
    return [
        c
        for c, t in events.schema.items()
        if t.is_numeric()
        and c not in skip
        and not c.endswith("_id")
        and (allowed is None or c in allowed)
    ]


def build_features(
    events: pl.DataFrame, allowlist: Sequence[str] | None = None
) -> pl.DataFrame:
    """Observable point-in-time features from ``events`` only (no label, no golden columns).

    Output: ``event_id`` + numeric features, same row order as ``events``, nulls/NaN filled
    (engineered -> 0, raw -> -1).
    """
    missing = [c for c in _REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"events is missing required columns: {missing}")
    ev = events.with_columns(pl.col("user_id").hash().alias("_user_code"))
    txn = ev.filter(pl.col("event_type") == 0)
    inv = ev.filter((pl.col("event_type") == 1) & pl.col("inviter_id").is_not_null())

    vel = rolling(
        txn,
        key="user_id",
        value="amount",
        windows_days=WINDOWS,
        aggs=["count", "sum", "mean", "max", "min"],
        prefix="obs_u_amt",
    )
    devu = rolling(
        txn,
        key="device_id",
        value="_user_code",
        windows_days=[7],
        aggs=["n_unique"],
        prefix="obs_dev_users",
    )
    churn = rolling(
        txn,
        key="user_id",
        value="user_state",
        windows_days=[30],
        aggs=["n_unique"],
        prefix="obs_u_state",
    )
    # a user's own activity as an inviter, evaluated exactly at each of the user's events
    invr = rolling_asof(
        ev.select("event_id", "user_id", "event_time"),
        inv.select("inviter_id", "event_time", "referral_bonus"),
        query_key="user_id",
        source_key="inviter_id",
        value="referral_bonus",
        windows_days=WINDOWS,
        aggs=["count", "sum", "mean", "max"],
        prefix="obs_invr_bonus",
    )
    # the inviter's recent invite activity as of the invite that brought a user in
    g = rolling(
        inv,
        key="inviter_id",
        value="referral_bonus",
        windows_days=[30],
        aggs=["count", "sum", "mean", "max"],
        prefix="obs_inv_bonus",
    )
    inv_feats = (
        inv.select("event_id", "user_id", "event_time")
        .join(g, on="event_id", how="left", maintain_order="left")
        .drop("event_id")
        .sort("event_time")
    )
    invitee = (
        ev.select("event_id", "user_id", "event_time")
        .sort("event_time")
        .join_asof(
            inv_feats, on="event_time", by="user_id", strategy="backward", check_sortedness=False
        )
        .drop("user_id", "event_time")
    )

    out = ev.select("event_id")
    for part in (vel, devu, churn, invr, invitee):
        out = out.join(part, on="event_id", how="left", maintain_order="left")
    engineered = [c for c in out.columns if c != "event_id"]
    out = out.with_columns(pl.col(engineered).fill_null(0))
    out = out.join(
        ev.select("event_id", "amount"), on="event_id", how="left", maintain_order="left"
    )
    out = out.with_columns(
        obs_amt_ratio_30d=pl.col("amount").fill_null(0.0) / (pl.col("obs_u_amt_mean_30d") + 1.0)
    ).drop("amount")

    raw = _raw_columns(events, allowlist)
    floats = [c for c in raw if events.schema[c].is_float()]
    raw_df = ev.select("event_id", *raw)
    if floats:
        raw_df = raw_df.with_columns(pl.col(floats).fill_nan(None))
    raw_df = raw_df.with_columns(pl.col(raw).fill_null(-1))
    return out.join(raw_df, on="event_id", how="left", maintain_order="left")
