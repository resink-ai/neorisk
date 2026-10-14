import math

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

_SCALARS = (
    "auc",
    "pr_auc",
    "recall_at_p50",
    "recall_at_p80",
    "precision_top_0_5pct",
    "precision_top_1pct",
    "lift_top_1pct",
    "ks",
    "log_loss",
    "brier",
)


def _downsample(*arrays, max_points: int):
    n = len(arrays[0])
    if n <= max_points:
        return [a.tolist() for a in arrays]
    idx = np.unique(np.linspace(0, n - 1, max_points).astype(int))
    return [a[idx].tolist() for a in arrays]


def _recall_at_precision(prec, rec, floor):
    ok = prec >= floor
    return float(rec[ok].max()) if ok.any() else 0.0


def _precision_top(y, p, frac):
    k = max(1, math.ceil(frac * len(y)))
    idx = np.argsort(-p, kind="stable")[:k]
    return float(y[idx].mean())


def _calibration(y, p, bins=10):
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return [{"mean_pred": float(p.mean()), "frac_pos": float(y.mean()), "count": len(y)}]
    which = np.clip(np.searchsorted(edges[1:-1], p, side="right"), 0, len(edges) - 2)
    out = []
    for b in range(len(edges) - 1):
        m = which == b
        if m.any():
            out.append(
                {
                    "mean_pred": float(p[m].mean()),
                    "frac_pos": float(y[m].mean()),
                    "count": int(m.sum()),
                }
            )
    return out


def best_f1_threshold(y, p) -> float:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype="float64")
    if len(np.unique(y)) < 2:
        return 0.5
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec[:-1] * rec[:-1] / np.maximum(prec[:-1] + rec[:-1], 1e-12)
    return float(thr[int(np.argmax(f1))])


def _confusion(y, p, threshold):
    pred = p >= threshold
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold),
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def compute_metrics(y, p, *, threshold: float | None = None, max_curve_points: int = 500) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype="float64")
    out: dict = {"n": len(y), "n_pos": int(y.sum())}
    if len(np.unique(y)) < 2:
        out.update({k: float("nan") for k in _SCALARS})
        out.update(
            roc_curve={"fpr": [], "tpr": []},
            pr_curve={"recall": [], "precision": []},
            calibration=[],
            confusion=None,
        )
        return out
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    eps = 1e-12
    pc = np.clip(p, eps, 1 - eps)
    base = float(y.mean())
    top1 = _precision_top(y, p, 0.01)
    f_fpr, f_tpr = _downsample(fpr, tpr, max_points=max_curve_points)
    f_rec, f_prec = _downsample(rec, prec, max_points=max_curve_points)
    out.update(
        auc=float(roc_auc_score(y, p)),
        pr_auc=float(average_precision_score(y, p)),
        recall_at_p50=_recall_at_precision(prec, rec, 0.5),
        recall_at_p80=_recall_at_precision(prec, rec, 0.8),
        precision_top_0_5pct=_precision_top(y, p, 0.005),
        precision_top_1pct=top1,
        lift_top_1pct=top1 / base if base > 0 else float("nan"),
        ks=float(np.max(tpr - fpr)),
        log_loss=float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))),
        brier=float(np.mean((p - y) ** 2)),
        roc_curve={"fpr": f_fpr, "tpr": f_tpr},
        pr_curve={"recall": f_rec, "precision": f_prec},
        calibration=_calibration(y, p),
        confusion=_confusion(y, p, threshold) if threshold is not None else None,
    )
    return out
