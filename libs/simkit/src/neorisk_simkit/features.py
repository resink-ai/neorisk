from collections.abc import Sequence

import polars as pl

_AGGS = {
    "count": lambda c: pl.col(c).count(),
    "sum": lambda c: pl.col(c).sum(),
    "mean": lambda c: pl.col(c).mean(),
    "max": lambda c: pl.col(c).max(),
    "min": lambda c: pl.col(c).min(),
    "n_unique": lambda c: pl.col(c).n_unique(),
}


def rolling(
    df: pl.DataFrame,
    *,
    key: str,
    value: str,
    windows_days: Sequence[int],
    aggs: Sequence[str],
    prefix: str,
    id_col: str = "event_id",
    time_col: str = "event_time",
) -> pl.DataFrame:
    """Per-key aggregates of ``value`` over the window [t - w days, t) (strictly before t)."""
    unknown = set(aggs) - set(_AGGS)
    if unknown:
        raise ValueError(f"unknown aggregations: {sorted(unknown)}")
    base = (
        df.filter(pl.col(key).is_not_null())
        .select(id_col, key, time_col, value)
        .sort([key, time_col], maintain_order=True)
    )
    out = base.select(id_col)
    if base.height == 0:
        return out.with_columns(
            [pl.lit(0.0).alias(f"{prefix}_{a}_{w}d") for w in windows_days for a in aggs]
        )
    for w in windows_days:
        r = base.rolling(index_column=time_col, period=f"{w}d", closed="left", group_by=key).agg(
            [_AGGS[a](value).alias(f"{prefix}_{a}_{w}d") for a in aggs]
        )
        if r.height != base.height or not (
            r[key].equals(base[key]) and r[time_col].equals(base[time_col])
        ):
            raise RuntimeError("rolling output is not row-aligned with its sorted input")
        out = out.hstack(r.drop(key, time_col))
    return out.with_columns(pl.exclude(id_col).fill_null(0))
