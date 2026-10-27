"""A sample from eth-collect (`data/eth/samples/toy/`), split labels, and per-address events.

Rules from the modeling plan:
- labels are noisy positives with a trust weight; unlabeled means unknown, never good
- a training label's transfers after its `observed_at` day are dropped (timing rule); held-out
  labels are unknown to the model, so their addresses keep their whole history
- `sample_reason` never reaches the model; it is used only to pick the evaluation pool
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import polars as pl

SERVICE_KINDS = ("exchange", "bridge", "mixer", "dex")
STABLE = {"USDT", "USDC", "DAI"}
HIGH_TRUST = 0.9


@dataclass(frozen=True)
class Sample:
    addresses: pl.DataFrame
    transfers: pl.DataFrame
    labels: pl.DataFrame

    @classmethod
    def read(cls, folder: Path) -> Sample:
        return cls(*(pl.read_parquet(folder / f"{t}.parquet")
                     for t in ("addresses", "transfers", "labels")))

    def risk(self) -> pl.DataFrame:
        """One row per risk-labeled address: best trust, its kinds, earliest observed_at."""
        return (self.labels.filter(pl.col("is_risk")).group_by("address").agg(
            pl.col("trust").max(), pl.col("label_kind").unique().sort().alias("kinds"),
            pl.col("observed_at").min()).sort("address"))

    def sampled(self) -> list[str]:
        """Seeds and random background: the evaluation pool (they share a selection
        process; counterparties have 1-2 transfers and would be found by length alone)."""
        return sorted(self.addresses.filter(
            pl.col("sample_reason").is_in(["seed", "random"]))["address"].to_list())


@dataclass(frozen=True)
class Split:
    train: dict[str, float]       # address -> trust, the positives the head may see
    holdout: set[str]             # high-trust positives hidden for recall@k
    kinds: dict[str, list[str]]   # address -> risk kinds, train and holdout alike


def split_labels(sample: Sample, *, holdout: float = 0.3, seed: int = 7) -> Split:
    """Hold out `holdout` of the high-trust risk addresses (OFAC, stablecoin freezes)."""
    risk = sample.risk()
    high = sorted(risk.filter(pl.col("trust") >= HIGH_TRUST)["address"].to_list())
    random.Random(seed).shuffle(high)
    held = set(high[: round(len(high) * holdout)])
    train = {a: t for a, t in risk.select("address", "trust").iter_rows() if a not in held}
    return Split(train, held, dict(risk.select("address", "kinds").iter_rows()))


def counterparty_types(sample: Sample) -> dict[str, str]:
    """EOA / contract from the rpc flag, overridden by a service label."""
    out = {a: ("contract" if c else "eoa") for a, c in
           sample.addresses.select("address", "is_contract").iter_rows() if c is not None}
    services = sample.labels.filter(pl.col("label_kind").is_in(SERVICE_KINDS))
    out.update(dict(services.select("address", "label_kind").iter_rows()))
    return out


def events(sample: Sample, known: dict[str, float] | None = None) -> pl.DataFrame:
    """Every transfer seen from each side: one row per (owner, transfer), time-ordered.
    `known` addresses lose events after their label's observed_at day (timing rule)."""
    tr = sample.transfers.with_columns(
        pl.when(pl.col("asset") == "ETH").then(pl.lit("eth"))
        .when(pl.col("asset_symbol").is_in(list(STABLE))).then(pl.lit("stable"))
        .otherwise(pl.lit("token")).alias("asset_class"))
    cols = ["ts", "block_number", "log_index", "kind", "asset_class", "amount", "usd_approx",
            "method_id", "status"]
    out_side = tr.select(*cols, pl.col("from_address").alias("owner"),
                         pl.col("to_address").alias("counterparty"),
                         pl.when(pl.col("from_address") == pl.col("to_address"))
                         .then(pl.lit("self")).otherwise(pl.lit("out")).alias("direction"))
    in_side = tr.filter(pl.col("from_address") != pl.col("to_address")).select(
        *cols, pl.col("to_address").alias("owner"), pl.col("from_address").alias("counterparty"),
        pl.lit("in").alias("direction"))
    ev = pl.concat([out_side, in_side]).filter(pl.col("owner").is_not_null())
    if known:
        cutoff = (sample.risk().filter(pl.col("address").is_in(list(known)))
                  .select(pl.col("address").alias("owner"), "observed_at"))
        ev = (ev.join(cutoff, on="owner", how="left")
              .filter(pl.col("observed_at").is_null()
                      | (pl.col("ts").dt.date() <= pl.col("observed_at")))
              .drop("observed_at"))
    return ev.sort(["owner", "ts", "block_number", "log_index"])
