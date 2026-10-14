import numpy as np

from neorisk_simkit.references import RefSpec, hubs, resolve_reference, skewed, uniform

T0 = np.datetime64("2026-01-01T00:00:00", "us")


def _created(n=100):
    return T0 + (np.arange(n) * 3_600_000_000).astype("timedelta64[us]")


def test_referenced_entity_predates_row():
    created = _created()
    times = created[10:] + np.timedelta64(1, "us")
    s = resolve_reference(RefSpec("r", "user", uniform), times, created, np.random.default_rng(0))
    idx = s.to_numpy()
    assert (created[idx] < times).all()


def test_strict_excludes_same_instant():
    created = _created()
    times = created[5:6]
    s = resolve_reference(RefSpec("r", "user", uniform), times, created, np.random.default_rng(0))
    assert s.to_numpy()[0] < 5


def test_no_eligible_entity_gives_null():
    created = _created()
    times = np.array([T0 - np.timedelta64(1, "D"), created[0]])
    s = resolve_reference(RefSpec("r", "user", uniform), times, created, np.random.default_rng(0))
    assert s.to_list() == [None, None]


def test_null_prob():
    created = _created()
    times = np.full(5000, created[-1] + np.timedelta64(1, "D"))
    spec = RefSpec("r", "user", uniform, null_prob=0.3)
    s = resolve_reference(spec, times, created, np.random.default_rng(0))
    assert 0.25 < s.null_count() / len(s) < 0.35


def test_hubs_concentrate_references():
    created = _created()
    times = np.full(5000, created[-1] + np.timedelta64(1, "D"))
    hub_idx = np.array([0, 1, 2])
    spec = RefSpec("r", "user", hubs(hub_idx, 0.5))
    idx = resolve_reference(spec, times, created, np.random.default_rng(0)).to_numpy()
    assert 0.45 < np.isin(idx, hub_idx).mean() < 0.6


def test_hubs_not_yet_created_are_not_chosen():
    created = _created()
    times = np.full(2000, created[1] + np.timedelta64(1, "us"))  # only idx 0,1 exist
    spec = RefSpec("r", "user", hubs(np.array([0, 50]), 1.0))
    idx = resolve_reference(spec, times, created, np.random.default_rng(0)).to_numpy()
    assert (idx == 0).all()


def test_skewed_favours_early_entities():
    m = np.full(10_000, 100)
    idx = skewed(3.0)(m, np.random.default_rng(0))
    assert idx.mean() < 30 and idx.max() < 100
