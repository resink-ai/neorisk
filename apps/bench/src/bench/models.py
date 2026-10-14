import copy
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

MODEL_ORDER = ("logreg", "rf", "xgb", "ann_small", "ann_large")
DISPLAY = {
    "logreg": "Logistic Regression",
    "rf": "Random Forest",
    "xgb": "XGBoost",
    "ann_small": "ANN small (32-16)",
    "ann_large": "ANN large (256-128-64)",
}
_KIND = {"logreg": "linear", "rf": "tree", "xgb": "xgb", "ann_small": "ann", "ann_large": "ann"}
_SCALED = {"logreg", "ann_small", "ann_large"}


@dataclass
class FittedModel:
    name: str
    kind: str
    estimator: Any
    scaler: StandardScaler | None
    train_seconds: float
    epochs: int | None = None

    def transform(self, x: np.ndarray) -> np.ndarray:
        return x if self.scaler is None else self.scaler.transform(x)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return self.estimator.predict_proba(self.transform(x))[:, 1].astype("float64")


@dataclass
class ModelFailure:
    name: str
    error: str


def _logreg(seed, pos_weight):
    return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)


def _rf(seed, pos_weight):
    return RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=20,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=seed,
    )


def _xgb(seed, pos_weight):
    return XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=pos_weight,
        eval_metric="aucpr",
        early_stopping_rounds=30,
        tree_method="hist",
        random_state=seed,
    )


def _ann(hidden, alpha):
    def make(seed, pos_weight):
        return MLPClassifier(
            hidden_layer_sizes=hidden,
            alpha=alpha,
            random_state=seed,
        )

    return make


_FACTORIES = {
    "logreg": _logreg,
    "rf": _rf,
    "xgb": _xgb,
    "ann_small": _ann((32, 16), 1e-4),
    "ann_large": _ann((256, 128, 64), 1e-4),
}


_ANN_EPOCHS = 60
_ANN_PATIENCE = 5
_ANN_BATCH = 1024


def _fit_ann(est, xt, y_train, xv, y_valid, seed):
    """Seeded partial_fit loop with validation-AUC early stopping; returns epochs run."""
    rng = np.random.default_rng(seed)
    y_train = np.asarray(y_train)
    y_valid = np.asarray(y_valid)
    use_val = len(np.unique(y_valid)) == 2
    best_auc, best_state, bad, epochs = -np.inf, None, 0, 0
    n = len(xt)
    for _ in range(_ANN_EPOCHS):
        idx = rng.permutation(n)
        for s in range(0, n, _ANN_BATCH):
            b = idx[s : s + _ANN_BATCH]
            est.partial_fit(xt[b], y_train[b], classes=[0, 1])
        epochs += 1
        if not use_val:
            continue
        auc = roc_auc_score(y_valid, est.predict_proba(xv)[:, 1])
        if auc > best_auc:
            best_auc, bad = auc, 0
            best_state = (copy.deepcopy(est.coefs_), copy.deepcopy(est.intercepts_))
        else:
            bad += 1
            if bad >= _ANN_PATIENCE:
                break
    if best_state is not None:
        est.coefs_, est.intercepts_ = best_state
    return epochs


def train_all(x_train, y_train, x_valid, y_valid, *, names=MODEL_ORDER, seed: int = 0):
    """Train each model; a failing model becomes a ``ModelFailure`` (never raises)."""
    out: dict[str, FittedModel | ModelFailure] = {}
    y_train = np.asarray(y_train)
    for name in names:
        try:
            if len(np.unique(y_train)) < 2:
                raise ValueError("training labels contain a single class")
            pos = max(int(y_train.sum()), 1)
            pos_weight = max((len(y_train) - pos) / pos, 1.0)
            est = _FACTORIES[name](seed, pos_weight)
            scaler = None
            xt, xv = x_train, x_valid
            if name in _SCALED:
                scaler = StandardScaler().fit(x_train)
                xt, xv = scaler.transform(x_train), scaler.transform(x_valid)
            t0 = time.perf_counter()
            epochs = None
            if name == "xgb":
                est.fit(xt, y_train, eval_set=[(xv, y_valid)], verbose=False)
            elif _KIND[name] == "ann":
                epochs = _fit_ann(est, xt, y_train, xv, y_valid, seed)
            else:
                est.fit(xt, y_train)
            out[name] = FittedModel(
                name, _KIND[name], est, scaler, time.perf_counter() - t0, epochs
            )
        except Exception as e:  # noqa: BLE001 - isolate per-model failures
            out[name] = ModelFailure(name, f"{type(e).__name__}: {e}")
    return out
