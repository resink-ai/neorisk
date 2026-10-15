import json
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


def load_events(data_dir: str | Path) -> tuple[pl.DataFrame, dict]:
    d = Path(data_dir)
    events = pl.read_parquet(d / "events.parquet")
    meta = json.loads((d / "meta.json").read_text())
    if "label" not in events.columns:
        raise ValueError("events.parquet has no label column")
    if "golden_columns" not in meta:
        raise ValueError("meta.json is missing required key 'golden_columns'")
    leaked = [c for c in meta["golden_columns"] if c in events.columns]
    if leaked:
        raise ValueError(f"golden columns found in events.parquet: {leaked}")
    return events, meta


def time_split(df: pl.DataFrame, fracs=(0.6, 0.2, 0.2)):
    """Chronological train/valid/test split; ties in time are broken by ``event_id``."""
    by = ["event_time", "event_id"] if "event_id" in df.columns else ["event_time"]
    df = df.sort(by, maintain_order=True)
    n = df.height
    a = int(n * fracs[0])
    b = a + int(n * fracs[1])
    return df[:a], df[a:b], df[b:]


def raw_features(df: pl.DataFrame) -> pl.DataFrame:
    cols = [
        c for c, t in df.schema.items() if t.is_numeric() and c != "label" and not c.endswith("_id")
    ]
    floats = [c for c in cols if df.schema[c].is_float()]
    return (
        df.select(cols)
        .with_columns(pl.col(floats).fill_nan(None))
        .with_columns(pl.col(cols).fill_null(-1))
    )


def evaluate(y: np.ndarray, p: np.ndarray, precision_floor: float = 0.5) -> dict:
    if len(np.unique(y)) < 2:
        nan = float("nan")
        return {"auc": nan, "pr_auc": nan, "recall_at_precision": nan}
    prec, rec, _ = precision_recall_curve(y, p)
    ok = prec >= precision_floor
    return {
        "auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "recall_at_precision": float(rec[ok].max()) if ok.any() else 0.0,
    }


def _models() -> dict:
    return {
        "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "xgb": lambda: XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1, n_jobs=1, tree_method="hist"
        ),
    }


def oracle_frame(events: pl.DataFrame, golden: pl.DataFrame) -> pl.DataFrame:
    """Events joined with golden columns except `score` (the label-generating probability)."""
    return events.join(golden.drop("score"), on="event_id")


def run(data_dir: str | Path, oracle: bool = False) -> list[dict]:
    events, _ = load_events(data_dir)
    feature_sets = {"raw": events}
    if oracle:
        golden = pl.read_parquet(Path(data_dir) / "golden.parquet")
        feature_sets["oracle"] = oracle_frame(events, golden)

    rows: list[dict] = []
    for fs_name, frame in feature_sets.items():
        tr, va, te = time_split(frame)
        splits = {"train": tr, "valid": va, "test": te}
        xs = {k: raw_features(v).to_numpy().astype("float64") for k, v in splits.items()}
        ys = {k: v["label"].to_numpy() for k, v in splits.items()}
        names = ["logreg", "xgb"] if fs_name == "raw" else ["xgb"]
        single_class = len(np.unique(ys["train"])) < 2
        for name in names:
            if single_class:  # nothing to learn: report NaN metrics rather than dropping rows
                nan = {
                    "auc": float("nan"),
                    "pr_auc": float("nan"),
                    "recall_at_precision": float("nan"),
                }
                rows.extend(
                    {"model": f"{name}_{fs_name}", "split": split, **nan}
                    for split in ("valid", "test")
                )
                continue
            model = _models()[name]()
            model.fit(xs["train"], ys["train"])
            for split in ("valid", "test"):
                p = model.predict_proba(xs[split])[:, 1]
                rows.append(
                    {"model": f"{name}_{fs_name}", "split": split, **evaluate(ys[split], p)}
                )
    return rows
