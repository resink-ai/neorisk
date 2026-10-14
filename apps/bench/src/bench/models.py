import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
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
            batch_size=1024,
            max_iter=60,
            # sklearn's early stopping scores accuracy, which stalls on imbalanced labels
            # and halts training near init; stop on training loss instead.
            early_stopping=False,
            n_iter_no_change=5,
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
            if name == "xgb":
                est.fit(xt, y_train, eval_set=[(xv, y_valid)], verbose=False)
            else:
                est.fit(xt, y_train)
            out[name] = FittedModel(name, _KIND[name], est, scaler, time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001 - isolate per-model failures
            out[name] = ModelFailure(name, f"{type(e).__name__}: {e}")
    return out
