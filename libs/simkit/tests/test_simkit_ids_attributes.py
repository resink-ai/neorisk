import time
import uuid

import numpy as np
import polars as pl
import pytest

from neorisk_simkit.attributes import AttrSpec, Cardinality, Volatility, sample_timeline
from neorisk_simkit.ids import make_uuids

T0 = np.datetime64("2026-01-01T00:00:00", "us")
T1 = T0 + np.timedelta64(90, "D")


def _timeline(spec, n=300, seed=0):
    created = np.full(n, T0)
    return sample_timeline(spec, created, T1, np.random.default_rng(seed))


def test_uuids_unique_and_deterministic():
    a = make_uuids(100, np.random.default_rng(1))
    b = make_uuids(100, np.random.default_rng(1))
    assert a == b and len(set(a)) == 100 and len(a[0]) == 36


def test_static_attribute_never_changes():
    df = _timeline(AttrSpec("os", Cardinality.LOW, Volatility.STATIC, k=4))
    assert df.height == 300
    assert df["value"].min() >= 0 and df["value"].max() < 4


def test_fast_changes_more_than_slow():
    slow = _timeline(AttrSpec("s", Cardinality.LOW, Volatility.SLOW, k=50))
    fast = _timeline(AttrSpec("f", Cardinality.LOW, Volatility.FAST, k=10))
    assert fast.height > slow.height > 300


def test_fast_low_cardinality_is_random_walk():
    df = _timeline(AttrSpec("battery", Cardinality.LOW, Volatility.FAST, k=10))
    steps = df.sort("idx", "valid_from").with_columns(d=pl.col("value").diff().over("idx"))
    assert steps["d"].drop_nulls().abs().max() <= 1


def test_first_row_at_created_at_and_sorted():
    created = np.sort(T0 + (np.arange(50) * 3600_000_000).astype("timedelta64[us]"))
    df = sample_timeline(
        AttrSpec("x", Cardinality.HIGH, Volatility.SLOW), created, T1, np.random.default_rng(3)
    )
    first = df.group_by("idx").agg(pl.col("valid_from").min()).sort("idx")
    assert (first["valid_from"].to_numpy() == created).all()
    assert df.equals(df.sort("idx", "valid_from"))
    assert df["value"].max() < 1_000_000


def test_same_seed_same_timeline():
    spec = AttrSpec("x", Cardinality.LOW, Volatility.FAST)
    assert _timeline(spec, seed=5).equals(_timeline(spec, seed=5))


def test_uuids_are_valid_v4_and_match_stdlib_semantics():
    ids = make_uuids(500, np.random.default_rng(9))
    raw = np.random.default_rng(9).bytes(16 * 500)
    ref = [str(uuid.UUID(bytes=raw[i * 16 : (i + 1) * 16], version=4)) for i in range(500)]
    assert ids == ref
    for s in ids:
        u = uuid.UUID(s)
        assert u.version == 4 and u.variant == uuid.RFC_4122 and str(u) == s


def test_uuids_fast_for_1m():
    t = time.perf_counter()
    ids = make_uuids(1_000_000, np.random.default_rng(0))
    assert time.perf_counter() - t < 2.0
    assert len(ids) == 1_000_000 and len(set(ids[:100_000])) == 100_000


def test_make_uuids_zero():
    assert make_uuids(0, np.random.default_rng(0)) == []


def test_fast_walk_reflects_and_does_not_stick_at_bounds():
    k = 5
    df = _timeline(AttrSpec("battery", Cardinality.LOW, Volatility.FAST, k=k), n=500)
    v = df["value"].to_numpy()
    assert v.min() >= 0 and v.max() <= k - 1
    steps = df.sort("idx", "valid_from").with_columns(d=pl.col("value").diff().over("idx"))
    d = steps["d"].drop_nulls()
    assert d.abs().max() <= 1
    # a reflecting walk never stays put at a bound (every change point moves the value)
    assert (d != 0).all()
    pinned = np.isin(v, [0, k - 1]).mean()
    assert pinned < 0.5  # uniform stationary share of the 2 bounds is ~2/5 for k=5


def test_fast_high_cardinality_walk_in_range_with_bounded_steps():
    spec = AttrSpec("ip", Cardinality.HIGH, Volatility.FAST)
    df = _timeline(spec, n=200)
    s = max(1, spec.size // 100)
    v = df["value"]
    assert v.min() >= 0 and v.max() <= spec.size - 1
    d = df.sort("idx", "valid_from").with_columns(d=pl.col("value").diff().over("idx"))["d"]
    assert d.drop_nulls().abs().max() <= s


def test_created_after_t1_raises():
    created = np.array([T1 + np.timedelta64(1, "D")])
    with pytest.raises(ValueError, match="created_at"):
        sample_timeline(AttrSpec("x"), created, T1, np.random.default_rng(0))


def test_attrspec_k_zero_or_one_raises():
    for k in (0, 1):
        with pytest.raises(ValueError, match="k must be"):
            _ = AttrSpec("x", k=k).size
