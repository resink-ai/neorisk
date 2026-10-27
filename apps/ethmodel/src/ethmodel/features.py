"""The hand-built baseline: about 20 aggregates per address from the same events the encoder
reads. If the transformer cannot beat these once data grows, the body needs work."""

from __future__ import annotations

import numpy as np
import polars as pl

NAMES = ("n_events", "n_in", "n_out", "n_self", "share_out", "n_external", "n_erc20",
         "n_stable", "n_token", "log_eth_in", "log_eth_out", "log_usd_in", "log_usd_out",
         "n_counterparties", "counterparty_ratio", "share_cp_contract", "share_cp_exchange",
         "share_cp_dex", "share_cp_bridge", "mixer_contact", "span_days", "log_median_gap",
         "failed_share")


def table(ev: pl.DataFrame, cp_types: dict[str, str]) -> pl.DataFrame:
    """address + one column per name in NAMES."""
    types = pl.DataFrame({"counterparty": list(cp_types), "cp_type": list(cp_types.values())},
                         schema={"counterparty": pl.String, "cp_type": pl.String})
    ev = ev.join(types, on="counterparty", how="left").with_columns(
        pl.col("cp_type").fill_null("unknown"),
        pl.col("ts").diff().over("owner").dt.total_seconds().alias("gap"))
    is_eth = pl.col("asset_class") == "eth"
    is_stable = pl.col("asset_class") == "stable"
    eth = pl.when(is_eth).then(pl.col("amount")).otherwise(0.0)
    usd = pl.when(is_stable).then(pl.col("usd_approx")).otherwise(0.0)
    d = pl.col("direction")
    agg = ev.group_by("owner").agg(
        pl.len().alias("n_events"),
        (d == "in").sum().alias("n_in"), (d == "out").sum().alias("n_out"),
        (d == "self").sum().alias("n_self"),
        (pl.col("kind") == "external").sum().alias("n_external"),
        (pl.col("kind") == "erc20").sum().alias("n_erc20"),
        is_stable.sum().alias("n_stable"), (pl.col("asset_class") == "token").sum().alias("n_token"),
        eth.filter(d == "in").sum().log1p().alias("log_eth_in"),
        eth.filter(d == "out").sum().log1p().alias("log_eth_out"),
        usd.filter(d == "in").sum().log1p().alias("log_usd_in"),
        usd.filter(d == "out").sum().log1p().alias("log_usd_out"),
        pl.col("counterparty").n_unique().alias("n_counterparties"),
        (pl.col("cp_type") == "contract").mean().alias("share_cp_contract"),
        (pl.col("cp_type") == "exchange").mean().alias("share_cp_exchange"),
        (pl.col("cp_type") == "dex").mean().alias("share_cp_dex"),
        (pl.col("cp_type") == "bridge").mean().alias("share_cp_bridge"),
        (pl.col("cp_type") == "mixer").any().cast(pl.Float64).alias("mixer_contact"),
        ((pl.col("ts").max() - pl.col("ts").min()).dt.total_seconds() / 86400).alias("span_days"),
        pl.col("gap").median().log1p().fill_null(0.0).alias("log_median_gap"),
        (pl.col("status") == 0).mean().fill_null(0.0).alias("failed_share"))
    agg = agg.with_columns((pl.col("n_out") / pl.col("n_events")).alias("share_out"),
                           (pl.col("n_counterparties") / pl.col("n_events"))
                           .alias("counterparty_ratio"))
    return agg.select(pl.col("owner").alias("address"), *[pl.col(n).cast(pl.Float64)
                                                         for n in NAMES]).fill_null(0.0)


def matrix(feats: pl.DataFrame) -> dict[str, np.ndarray]:
    x = feats.select(NAMES).to_numpy()
    return dict(zip(feats["address"].to_list(), x))
