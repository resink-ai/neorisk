import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from bench.explain import explain_model, stratified_sample
from bench.features import build_features, feature_names
from bench.metrics import best_f1_threshold, compute_metrics
from bench.models import DISPLAY, MODEL_ORDER, FittedModel, describe, train_all
from bench.report import render_report, to_jsonable
from bench.runner import load_events, time_split


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg, file=sys.stderr, flush=True)


def _observed(events) -> dict:
    """Counts realised in the data, for the report's data-generation section."""
    out = {}
    for col, key in (
        ("user_id", "n_users"),
        ("device_id", "n_devices"),
        ("product_id", "n_products"),
    ):
        if col in events.columns:
            out[key] = int(events[col].drop_nulls().n_unique())
    if "event_type" in events.columns:
        out["n_txn"] = int((events["event_type"] == 0).sum())
        out["n_invite"] = int((events["event_type"] == 1).sum())
    out["n_bad"] = int(events["label"].sum())
    return out


def run_compare(
    data_dir,
    *,
    models=MODEL_ORDER,
    shap_rows: int = 5000,
    ann_shap_rows: int = 1000,
    seed: int = 0,
    min_train_pos: int = 50,
    verbose: bool = False,
) -> dict:
    """Train and evaluate ``models`` on ``events.parquet`` (``golden.parquet`` is never read).

    Returns the ``results`` dict consumed by :func:`bench.report.render_report`.
    """
    t_start = time.perf_counter()
    events, meta = load_events(data_dir)  # guards: label present, no golden leakage
    t0 = time.perf_counter()
    feats = build_features(events, meta["_allowlist"])
    names = feature_names(feats)
    feature_seconds = time.perf_counter() - t0
    _log(verbose, f"features: {len(names)} columns in {feature_seconds:.1f}s")

    df = events.select("event_id", "event_time", "label").join(
        feats, on="event_id", how="left", maintain_order="left"
    )
    tr, va, te = time_split(df)
    splits = {"train": tr, "valid": va, "test": te}
    x = {k: v.select(names).to_numpy().astype("float64") for k, v in splits.items()}
    y = {k: v["label"].to_numpy().astype(int) for k, v in splits.items()}
    if y["train"].sum() < min_train_pos:
        print(
            f"warning: only {int(y['train'].sum())} positives in train (< {min_train_pos})",
            file=sys.stderr,
        )

    t0 = time.perf_counter()
    fitted = train_all(
        x["train"], y["train"], x["valid"], y["valid"], names=tuple(models), seed=seed
    )
    train_total = time.perf_counter() - t0
    _log(verbose, f"trained {len(fitted)} models in {train_total:.1f}s")

    sample_idx = stratified_sample(y["test"], shap_rows, np.random.default_rng(seed))
    out_models: dict = {}
    for name, m in fitted.items():
        entry = {
            "display": DISPLAY[name],
            "failed": None,
            "train_seconds": 0.0,
            "infer_seconds": 0.0,
            "shap_seconds": 0.0,
            "epochs": None,
            "model_info": describe(name),
            "mean_pred": None,
            "metrics": None,
            "valid_metrics": None,
            "shap": None,
        }
        if not isinstance(m, FittedModel):
            entry["failed"] = m.error
            out_models[name] = entry
            _log(verbose, f"{name}: FAILED {m.error}")
            continue
        entry["train_seconds"] = float(m.train_seconds)
        entry["epochs"] = m.epochs
        p_valid = m.predict_proba(x["valid"])
        t0 = time.perf_counter()
        p_test = m.predict_proba(x["test"])  # infer_seconds: test split only
        entry["infer_seconds"] = float(time.perf_counter() - t0)
        entry["model_info"]["epochs"] = m.epochs
        entry["mean_pred"] = float(np.mean(p_test)) if len(p_test) else None
        thr = best_f1_threshold(y["valid"], p_valid)
        entry["valid_metrics"] = compute_metrics(y["valid"], p_valid, threshold=thr)
        entry["metrics"] = compute_metrics(y["test"], p_test, threshold=thr)
        t0 = time.perf_counter()
        try:
            entry["shap"] = explain_model(
                m, x["train"], x["test"][sample_idx], names, ann_rows=ann_shap_rows, seed=seed
            )
        except Exception as e:  # noqa: BLE001 - SHAP failure must not drop the model
            entry["shap"] = None
            entry["shap_error"] = f"{type(e).__name__}: {e}"
        entry["shap_seconds"] = float(time.perf_counter() - t0)
        out_models[name] = entry
        _log(
            verbose,
            f"{name}: auc={entry['metrics']['auc']:.4f} train={entry['train_seconds']:.1f}s "
            f"infer={entry['infer_seconds']:.1f}s shap={entry['shap_seconds']:.1f}s",
        )

    return {
        "run": {
            "data_dir": str(data_dir),
            "n_events": int(events.height),
            "n_features": len(names),
            "feature_names": names,
            "split_sizes": {"train": tr.height, "valid": va.height, "test": te.height},
            "bad_rate": float(events["label"].mean()),
            "seed": seed,
            "shap_rows": len(sample_idx),
            "shap_sample_pos_rate": float(y["test"][sample_idx].mean())
            if len(sample_idx)
            else None,
            "test_bad_rate": float(y["test"].mean()) if len(y["test"]) else None,
            "train_positives": int(y["train"].sum()),
            "min_train_pos": min_train_pos,
            "test_rows": len(y["test"]),
            "ann_shap_rows": ann_shap_rows,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "dataset_meta": {
                **{k: meta.get(k) for k in ("scenario", "seed", "n_events", "bad_rate")},
                "config": meta.get("config"),
                "observed": _observed(events),
            },
            "timings": {
                "feature_seconds": float(feature_seconds),
                "train_all_seconds": float(train_total),
                "total_seconds": float(time.perf_counter() - t_start),
            },
        },
        "models": out_models,
    }


def write_outputs(results: dict, html_path, json_path=None, *, lang: str = "zh") -> None:
    html_path = Path(html_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_report(results, lang=lang), encoding="utf-8")
    if json_path:
        json_path = Path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(to_jsonable(results), indent=2, allow_nan=False), encoding="utf-8"
        )
