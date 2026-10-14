import json
import math
import re
import xml.etree.ElementTree as ET

from bench.report import render_report, svg_lines, to_jsonable


def _metrics(auc):
    return {
        "n": 1000,
        "n_pos": 20,
        "auc": auc,
        "pr_auc": auc / 3,
        "recall_at_p50": 0.3,
        "recall_at_p80": 0.1,
        "precision_top_0_5pct": 0.5,
        "precision_top_1pct": 0.4,
        "lift_top_1pct": 20.0,
        "ks": 0.4,
        "log_loss": 0.2,
        "brier": 0.02,
        "roc_curve": {"fpr": [0, 0.5, 1], "tpr": [0, 0.8, 1]},
        "pr_curve": {"recall": [0, 0.5, 1], "precision": [1, 0.6, 0.02]},
        "calibration": [
            {"mean_pred": 0.01, "frac_pos": 0.012, "count": 500},
            {"mean_pred": 0.2, "frac_pos": 0.15, "count": 500},
        ],
        "confusion": {
            "threshold": 0.3,
            "tn": 900,
            "fp": 80,
            "fn": 5,
            "tp": 15,
            "precision": 0.15,
            "recall": 0.75,
            "f1": 0.25,
        },
    }


def _shap(top):
    feats = [top, "b", "c"]
    return {
        "method": "TreeExplainer",
        "n_rows": 100,
        "importance": {top: 1.0, "b": 0.3, "c": 0.01},
        "quantiles": {f: [-1, -0.5, 0, 0.5, 1] for f in feats},
        "points": {f: {"shap": [-1, 0, 1], "value": [0, 0.5, 1]} for f in feats},
    }


def _results():
    models = {}
    for name, auc in [("logreg", 0.7), ("rf", 0.8), ("xgb", 0.85), ("ann_small", 0.75)]:
        models[name] = {
            "display": name.upper(),
            "failed": None,
            "train_seconds": 1.0,
            "infer_seconds": 0.1,
            "metrics": _metrics(auc),
            "valid_metrics": _metrics(auc),
            "shap": _shap("amount"),
        }
    models["ann_small"]["epochs"] = 17
    models["ann_large"] = {
        "display": "ANN large",
        "failed": "RuntimeError: boom<script>",
        "train_seconds": 0.0,
        "infer_seconds": 0.0,
        "metrics": None,
        "valid_metrics": None,
        "shap": None,
    }
    return {
        "run": {
            "data_dir": "data/x",
            "n_events": 1000,
            "n_features": 3,
            "feature_names": ["amount", "b", "c"],
            "split_sizes": {"train": 600, "valid": 200, "test": 200},
            "bad_rate": 0.02,
            "seed": 0,
            "generated_at": "2026-10-14",
        },
        "models": models,
    }


def test_report_contains_all_models_and_sections():
    html = render_report(_results(), lang="en")
    for token in ("LOGREG", "RF", "XGB", "ANN_SMALL", "ROC", "PR", "SHAP", "Calibration"):
        assert token in html
    assert html.count("<svg") >= 4
    assert "failed" in html.lower() and "amount" in html
    assert "ANN large" in html and "17" in html  # failed model listed, epochs shown


def test_report_is_self_contained_and_escapes_text():
    html = render_report(_results(), lang="zh")
    assert not re.search(r"https?://", html)
    assert "<script src" not in html and "<link" not in html
    assert "<script" not in html and "@import" not in html
    assert "&lt;script&gt;" in html and "boom<script>" not in html


def test_report_renders_with_nan_metrics_and_without_shap():
    r = _results()
    r["models"]["rf"]["metrics"].update(auc=float("nan"), pr_auc=float("nan"))
    r["models"]["xgb"]["shap"] = None
    html = render_report(r, lang="en")
    body = html.split("<body>")[1]
    assert "NaN" not in body and not re.search(r"\bnan\b", body.lower())
    assert "\u2014" in body and "unavailable" in body.lower()


def test_report_renders_when_every_model_failed():
    r = _results()
    for m in r["models"].values():
        m.update(failed="boom", metrics=None, valid_metrics=None, shap=None)
    html = render_report(r, lang="en")
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    assert "boom" in html


def test_to_jsonable_replaces_nonfinite_and_numpy():
    import numpy as np

    obj = {
        "a": float("nan"),
        "b": [np.float64(1.5), np.int64(3), float("inf")],
        "c": np.array([1, 2]),
    }
    out = to_jsonable(obj)
    assert out == {"a": None, "b": [1.5, 3, None], "c": [1, 2]}
    json.dumps(out, allow_nan=False)


def test_svg_lines_is_well_formed():
    s = svg_lines(
        [{"name": "m", "color": "#2f6fed", "xs": [0, 1], "ys": [0, 1]}],
        xlabel="FPR",
        ylabel="TPR",
        diagonal=True,
    )
    assert s.startswith("<svg") and s.rstrip().endswith("</svg>") and "polyline" in s
    root = ET.fromstring(s)  # parses as XML
    assert root.tag == "svg"
    poly = [e for e in root.iter() if e.tag == "polyline"]
    assert len(poly) == 1 and poly[0].get("stroke") == "#2f6fed"
    assert "nan" not in s.lower()
    assert "FPR" in s and "TPR" in s
    assert not math.isnan(float(root.get("viewBox").split()[2]))
