import numpy as np
import polars as pl

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
