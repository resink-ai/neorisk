from dataclasses import dataclass

import numpy as np
import polars as pl

from neorisk_simkit.attributes import AttrSpec, sample_timeline
from neorisk_simkit.ids import make_uuids


@dataclass(frozen=True)
class EntitySpec:
    name: str
    n: int
    attrs: tuple[AttrSpec, ...]
    created_frac: float = 0.5  # entities are created within the first created_frac of the span


@dataclass
class EntityTable:
    name: str
    ids: pl.DataFrame  # idx (rank by created_at), entity_id (UUID), created_at
    attrs: pl.DataFrame  # idx, attr, valid_from, value (long form)

    @property
    def n(self) -> int:
        return self.ids.height

    def created_at(self) -> np.ndarray:
        return self.ids["created_at"].to_numpy()


def build_entities(
    spec: EntitySpec, t0: np.datetime64, t1: np.datetime64, rng: np.random.Generator
) -> EntityTable:
    span_us = int((t1 - t0) / np.timedelta64(1, "us"))
    offs = (rng.random(spec.n) * spec.created_frac * span_us).astype("int64")
    created = np.sort(t0 + offs.astype("timedelta64[us]"))
    ids = pl.DataFrame(
        {
            "idx": np.arange(spec.n, dtype="int64"),
            "entity_id": make_uuids(spec.n, rng),
            "created_at": created,
        }
    )
    parts = [
        sample_timeline(a, created, t1, rng).with_columns(attr=pl.lit(a.name)) for a in spec.attrs
    ]
    attrs = pl.concat(parts).select("idx", "attr", "valid_from", "value")
    return EntityTable(spec.name, ids, attrs)


def attach_asof(
    events: pl.DataFrame,
    table: EntityTable,
    *,
    idx_col: str,
    time_col: str = "event_time",
    prefix: str | None = None,
) -> pl.DataFrame:
    """Add each attribute's value as-of ``time_col`` for the entity in ``idx_col``.

    Adds one column ``{prefix}_{attr}`` per attribute (latest ``valid_from <= time``);
    null ``idx_col`` rows get nulls. Row order is preserved. Raises ``ValueError`` if an
    output column already exists in ``events``.
    """
    prefix = prefix or table.name
    clash = [
        f"{prefix}_{a}"
        for a in table.attrs["attr"].unique(maintain_order=True)
        if f"{prefix}_{a}" in events.columns
    ]
    if clash:
        raise ValueError(f"attach_asof would overwrite existing columns: {clash}")
    base = events.with_row_index("_row")
    # join_asof cannot take null `by` keys: join only non-null rows, left-join back on _row.
    left = base.filter(pl.col(idx_col).is_not_null()).sort(time_col)
    idx_dtype = left[idx_col].dtype
    added = []
    for attr in table.attrs["attr"].unique(maintain_order=True):
        right = (
            table.attrs.filter(pl.col("attr") == attr)
            .select(
                pl.col("idx").cast(idx_dtype).alias(idx_col),
                pl.col("valid_from").cast(left[time_col].dtype).alias(time_col),
                pl.col("value").alias(f"{prefix}_{attr}"),
            )
            .sort(time_col)
        )
        left = left.join_asof(
            right, on=time_col, by=idx_col, strategy="backward", check_sortedness=False
        )
        added.append(f"{prefix}_{attr}")
    return base.join(left.select("_row", *added), on="_row", how="left").sort("_row").drop("_row")


def map_ids(table: EntityTable, idx: pl.Series) -> pl.Series:
    """Entity idx -> UUID string; null idx stays null."""
    valid = idx.is_not_null().to_numpy()
    out = np.full(len(idx), None, dtype=object)
    ids = table.ids["entity_id"].to_numpy()
    out[valid] = ids[idx.filter(idx.is_not_null()).to_numpy()]
    return pl.Series(idx.name, out.tolist(), dtype=pl.Utf8)  # list: avoid Object inference
