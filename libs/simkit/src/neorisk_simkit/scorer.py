from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np
import polars as pl
import xgboost as xgb

_EPS = 1e-6


class Scorer(Protocol):
    def score(self, golden: pl.DataFrame) -> np.ndarray: ...


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _zscore(golden: pl.DataFrame, cols: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    x = golden.select(list(cols)).to_numpy().astype("float64")
    sd = x.std(axis=0)
    sd[sd == 0] = 1.0  # zero-variance column -> contributes 0 after centring
    return x, (x - x.mean(axis=0)) / sd


class XGBScorer:
    def __init__(
        self,
        weights: Mapping[str, float],
        seed: int = 0,
        n_estimators: int = 60,
        max_depth: int = 3,
    ):
        self.weights = dict(weights)
        self.seed = seed
        self.n_estimators = n_estimators
        self.max_depth = max_depth

    def score(self, golden: pl.DataFrame) -> np.ndarray:
        cols = list(self.weights)
        x, z = _zscore(golden, cols)
        teacher = _sigmoid(np.tanh(z) @ np.array([self.weights[c] for c in cols]))
        params = {
            "max_depth": self.max_depth,
            "eta": 0.2,
            "seed": self.seed,
            "nthread": 1,
            "tree_method": "hist",
            "objective": "reg:squarederror",
        }
        dmat = xgb.DMatrix(x, label=teacher)
        booster = xgb.train(params, dmat, num_boost_round=self.n_estimators)
        return np.clip(booster.predict(dmat), _EPS, 1 - _EPS).astype("float64")


class MLPScorer:
    def __init__(self, columns: Sequence[str], hidden: int = 16, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.columns = list(columns)
        self.w1 = rng.normal(size=(len(self.columns), hidden)) / np.sqrt(len(self.columns))
        self.b1 = rng.normal(size=hidden) * 0.1
        self.w2 = rng.normal(size=hidden) / np.sqrt(hidden)

    def score(self, golden: pl.DataFrame) -> np.ndarray:
        _, z = _zscore(golden, self.columns)
        logit = np.tanh(z @ self.w1 + self.b1) @ self.w2 * 2.0
        return np.clip(_sigmoid(logit), _EPS, 1 - _EPS)


def calibrate(p: np.ndarray, target_rate: float, iters: int = 60) -> np.ndarray:
    """Shift logits by a constant so the mean probability equals ``target_rate``."""
    if not 0 < target_rate < 1:
        raise ValueError("target_rate must be in (0, 1)")
    p = np.clip(p, _EPS, 1 - _EPS)
    logit = np.log(p / (1 - p))
    lo, hi = -30.0, 30.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        if _sigmoid(logit + mid).mean() > target_rate:
            hi = mid
        else:
            lo = mid
    return _sigmoid(logit + (lo + hi) / 2)


def sample_labels(p: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return (rng.random(len(p)) < p).astype("int64")
