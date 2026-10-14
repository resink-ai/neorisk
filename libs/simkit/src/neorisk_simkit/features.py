from collections.abc import Sequence

import polars as pl

# Nulls in ``value`` are ignored by every aggregation (count = number of non-null values).
_AGGS = {
    "count": lambda c: pl.col(c).count(),
    "sum": lambda c: pl.col(c).sum(),
    "mean": lambda c: pl.col(c).mean(),
    "max": lambda c: pl.col(c).max(),
    "min": lambda c: pl.col(c).min(),
    "n_unique": lambda c: pl.col(c).drop_nulls().n_unique(),
}
_INT_AGGS = {"count", "n_unique"}


def _dtype(agg: str) -> pl.DataType:
    return pl.Int64 if agg in _INT_AGGS else pl.Float64


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
    """Per-key aggregates of ``value`` over the window [t - w days, t) (strictly before t).

    Rows sharing a key and the exact same time are excluded from each other's window.
    Rows with a null ``key`` are dropped. Null ``value`` entries are ignored by every
    aggregation. Empty windows give 0.

    Returns ``id_col`` plus one column ``{prefix}_{agg}_{w}d`` per window and aggregation,
    one row per non-null-key input row, ordered by ``[key, time_col]`` (stable for ties).
    ``count``/``n_unique`` columns are Int64 and all others Float64, also for empty input.
    """
    unknown = set(aggs) - set(_AGGS)
    if unknown:
        raise ValueError(f"unknown aggregations: {sorted(unknown)}")
    base = (
        df.filter(pl.col(key).is_not_null())
        .select(id_col, key, time_col, value)
        .sort([key, time_col], maintain_order=True)
    )
    out = base.select(id_col)
    names = {f"{prefix}_{a}_{w}d": a for w in windows_days for a in aggs}
    if base.height == 0:
        return out.with_columns([pl.lit(None, dtype=_dtype(a)).alias(n) for n, a in names.items()])
    for w in windows_days:
        r = base.rolling(index_column=time_col, period=f"{w}d", closed="left", group_by=key).agg(
            [_AGGS[a](value).alias(f"{prefix}_{a}_{w}d") for a in aggs]
        )
        if r.height != base.height or not (
            r[key].equals(base[key]) and r[time_col].equals(base[time_col])
        ):
            raise RuntimeError("rolling output is not row-aligned with its sorted input")
        out = out.hstack(r.drop(key, time_col))
    return out.with_columns([pl.col(n).fill_null(0).cast(_dtype(a)) for n, a in names.items()])
