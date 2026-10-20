"""Load any datagen dataset for modeling, with label maturity.

`load_rows` turns one event table into model rows: numeric and categorical columns become
features (ids excluded), and the hidden labels join on a key column. Each row carries its
final label and `label_available_at`. `maturity_split` trains only on labels known at the
cutoff: a positive whose label arrives after the cutoff counts as negative for training,
as it would in production. The test window after the cutoff is scored with final labels.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

from neorisk_simkit.io import read

COMMON = {"event_id", "event_type", "event_time", "seq", "partition_id", "cause_id",
          "action_id"}


def load_rows(run_dir: str | Path, event: str, key: str,
              roles: list[str] | None = None) -> pl.DataFrame:
    run = read(run_dir)
    df = run.events[event]
    lab = run.labels
    if roles:
        lab = lab.filter(pl.col("role").is_in(roles))
    lab = lab.select(pl.col("target_id").alias(key), pl.lit(1).alias("label"),
                     "label_available_at")
    feats = [c for c, t in df.schema.items()
             if c not in COMMON and c != key and not c.endswith("_id")
             and (t.is_numeric() or isinstance(t, pl.Enum))]
    return (df.select("event_id", "event_time", key, *feats)
            .with_columns(pl.col(pl.Enum).to_physical().cast(pl.Int64))
            .join(lab, on=key, how="left")
            .with_columns(pl.col("label").fill_null(0)).sort("event_time"))


def maturity_split(rows: pl.DataFrame, cutoff_day: float, test_days: float = 14.0
                   ) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(train, test). Train: rows before the cutoff, with `label_obs`, the label as known at
    the cutoff. Test: rows in [cutoff, cutoff + test_days), with final labels."""
    t0 = rows["event_time"].min()
    cut = t0 + timedelta(days=cutoff_day)
    end = cut + timedelta(days=test_days)
    train = rows.filter(pl.col("event_time") < cut).with_columns(
        label_obs=((pl.col("label") == 1) & (pl.col("label_available_at") <= cut)).cast(pl.Int64))
    test = rows.filter((pl.col("event_time") >= cut) & (pl.col("event_time") < end))
    return train, test


def features(df: pl.DataFrame) -> list[str]:
    skip = {"event_id", "event_time", "label", "label_obs", "label_available_at"}
    return [c for c, t in df.schema.items() if c not in skip and t.is_numeric()
            and not c.endswith("_id")]


def run_maturity(run_dir: str | Path, event: str, key: str, roles: list[str] | None = None,
                 cutoff_day: float = 60.0, test_days: float = 14.0, seed: int = 0) -> dict:
    """Train XGBoost on labels as known at the cutoff, and (for contrast) on final labels,
    which leak the future; score both on the test window with final labels."""
    from xgboost import XGBClassifier

    from bench.runner import evaluate

    rows = load_rows(run_dir, event, key, roles)
    train, test = maturity_split(rows, cutoff_day, test_days)
    cols = features(rows)
    x_tr, x_te = train.select(cols).to_numpy(), test.select(cols).to_numpy()
    out = {"event": event, "key": key, "cutoff_day": cutoff_day, "features": cols,
           "n_train": train.height, "n_test": test.height,
           "train_positives_final": int(train["label"].sum()),
           "train_positives_known_at_cutoff": int(train["label_obs"].sum()),
           "test_positives": int(test["label"].sum())}
    for name, y in (("known_at_cutoff", "label_obs"), ("final_leaky", "label")):
        m = XGBClassifier(n_estimators=150, max_depth=4, learning_rate=0.1, random_state=seed,
                          n_jobs=1, eval_metric="logloss")
        m.fit(x_tr, train[y].to_numpy())
        out[name] = evaluate(test["label"].to_numpy(), m.predict_proba(x_te)[:, 1])
    return out
