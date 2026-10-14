import numpy as np

from bench.models import MODEL_ORDER, FittedModel, ModelFailure, train_all


def _data(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 4))
    x[:, 3] = 1.0  # constant column (zero variance)
    logit = 2.0 * x[:, 0] - 1.0 * x[:, 1] - 3.0
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return x, y


def test_all_five_models_train_and_predict_probabilities():
    x, y = _data()
    tr, va = slice(0, 2000), slice(2000, 3000)
    res = train_all(x[tr], y[tr], x[va], y[va], seed=1)
    assert list(res) == list(MODEL_ORDER)
    for name, m in res.items():
        assert isinstance(m, FittedModel), (name, getattr(m, "error", None))
        p = m.predict_proba(x[va])
        assert p.shape == (1000,) and np.isfinite(p).all()
        assert p.min() >= 0 and p.max() <= 1
        assert m.train_seconds >= 0


def test_models_beat_chance_on_signal():
    from sklearn.metrics import roc_auc_score

    x, y = _data(6000, seed=3)
    tr, te = slice(0, 4000), slice(4000, 6000)
    res = train_all(x[tr], y[tr], x[tr], y[tr], seed=0)
    for name, m in res.items():
        assert roc_auc_score(y[te], m.predict_proba(x[te])) > 0.7, name


def test_deterministic_with_seed():
    x, y = _data()
    a = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg", "ann_small"), seed=4)
    b = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg", "ann_small"), seed=4)
    for n in a:
        assert np.allclose(a[n].predict_proba(x[2000:]), b[n].predict_proba(x[2000:]))


def test_failure_is_captured_not_raised(monkeypatch):
    import bench.models as m

    def boom(*a, **k):
        raise RuntimeError("kaput")

    monkeypatch.setitem(m._FACTORIES, "rf", boom)
    x, y = _data()
    res = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg", "rf"), seed=0)
    assert isinstance(res["logreg"], FittedModel)
    assert isinstance(res["rf"], ModelFailure) and "kaput" in res["rf"].error


def test_single_class_train_is_a_failure_not_a_crash():
    x, _ = _data()
    y = np.zeros(len(x), dtype=int)
    res = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg",), seed=0)
    assert isinstance(res["logreg"], ModelFailure)
