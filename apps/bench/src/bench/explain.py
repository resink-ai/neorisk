import numpy as np
import shap

from bench.models import SHAP_INFO, FittedModel

_QS = (5, 25, 50, 75, 95)
_KERNEL_NSAMPLES = 1000


def stratified_sample(y: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Up to ``n`` rows: all positives (capped at n // 2) plus random negatives."""
    y = np.asarray(y).astype(int)
    if len(y) <= n:
        return np.arange(len(y))
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    n_pos = min(len(pos), n // 2)
    pos_pick = rng.choice(pos, n_pos, replace=False) if n_pos < len(pos) else pos
    neg_pick = rng.choice(neg, min(len(neg), n - n_pos), replace=False)
    return np.sort(np.concatenate([pos_pick, neg_pick]))


def _positive_class(sv) -> np.ndarray:
    if isinstance(sv, list):
        return np.asarray(sv[-1])
    sv = np.asarray(sv)
    return sv[:, :, -1] if sv.ndim == 3 else sv


def _shap_values(model: FittedModel, x_train, x_explain, ann_rows, seed):
    """Return (shap values, method, row indices of ``x_explain`` actually explained).

    Units differ per method: linear and xgb are in log-odds; RF (tree) and ANN (kernel) are in
    probability. Importances are therefore not comparable across models without normalisation.
    """
    rows = np.arange(len(x_explain))
    xe = model.transform(x_explain)
    if model.kind in ("tree", "xgb"):
        sv = shap.TreeExplainer(model.estimator).shap_values(xe)
        return _positive_class(sv), "TreeExplainer", rows
    xt = model.transform(x_train)
    if model.kind == "linear":
        sv = shap.LinearExplainer(model.estimator, xt).shap_values(xe)
        return _positive_class(sv), "LinearExplainer", rows
    if len(xe) > ann_rows:
        rows = np.sort(np.random.default_rng(seed).choice(len(xe), ann_rows, replace=False))
    if len(xt) > 2000:
        xt = shap.sample(xt, 2000, random_state=seed)
    bg = shap.kmeans(xt, 10)
    explainer = shap.KernelExplainer(lambda a: model.estimator.predict_proba(a)[:, 1], bg)
    # KernelExplainer samples coalitions from the global np.random state: seed it, then restore
    state = np.random.get_state()
    np.random.seed(seed)
    try:
        sv = explainer.shap_values(xe[rows], nsamples=_KERNEL_NSAMPLES, l1_reg=False, silent=True)
    finally:
        np.random.set_state(state)
    return _positive_class(sv), "KernelExplainer", rows


def explain_model(
    model: FittedModel,
    x_train,
    x_explain,
    feature_names,
    *,
    ann_rows: int = 1000,
    seed: int = 0,
    max_points: int = 300,
) -> dict:
    x_explain = np.asarray(x_explain, dtype="float64")
    sv, method, rows = _shap_values(model, np.asarray(x_train), x_explain, ann_rows, seed)
    sv = np.nan_to_num(np.asarray(sv, dtype="float64"), nan=0.0, posinf=0.0, neginf=0.0)
    # colouring values: original (unscaled) scale of exactly the explained rows, normalised 0..1
    raw = x_explain[rows]
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(sv), min(len(sv), max_points), replace=False))
    out = {
        "method": method,
        "unit": SHAP_INFO[model.kind][1],
        "n_rows": len(sv),
        "importance": {},
        "quantiles": {},
        "points": {},
    }
    for j, name in enumerate(feature_names):
        col = sv[:, j]
        out["importance"][name] = float(np.mean(np.abs(col)))
        out["quantiles"][name] = [float(v) for v in np.percentile(col, _QS)]
        v = raw[:, j]
        lo, hi = float(v.min()), float(v.max())
        norm = (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v)
        out["points"][name] = {
            "shap": col[pick].astype(float).tolist(),
            "value": norm[pick].astype(float).tolist(),
        }
    return out
