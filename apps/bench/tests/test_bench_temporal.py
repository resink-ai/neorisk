import numpy as np

from bench.temporal_sim import TemporalConfig, generate_temporal


def _small():
    return generate_temporal(TemporalConfig(n_events=20_000, n_users=3_000, seed=3))


def test_temporal_sim_is_deterministic_and_has_delays_only_for_bad():
    a, b = _small(), _small()
    assert a.equals(b)
    bad = a["label"].to_numpy() == 1
    d = a["label_delay_days"].to_numpy()
    assert np.isfinite(d[bad]).all() and np.isnan(d[~bad]).all()
    assert 0.01 < bad.mean() < 0.08


def test_leak_columns_are_strong_offline_but_pit_values_are_causal():
    df = _small()
    y = df["label"].to_numpy()
    snap = df["acct_closed_flag"].to_numpy()
    pit = df["acct_closed_flag_pit"].to_numpy()
    assert snap[y == 1].mean() == 1.0  # a bad event's own user is always flagged in the snapshot
    assert pit[y == 1].mean() < 0.5  # at event time it is mostly not yet known
    assert (df["fut_txn_cnt_30d_pit"].to_numpy() == 0).all()
