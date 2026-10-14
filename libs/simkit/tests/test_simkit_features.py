import numpy as np
import polars as pl
import pytest

from neorisk_simkit.features import rolling

T0 = np.datetime64("2026-01-01T00:00:00", "us")


def _frame(n=300, n_keys=7, seed=0, with_ties=True):
    rng = np.random.default_rng(seed)
    hours = rng.integers(0, 24 * 40, n) if with_ties else rng.permutation(24 * 40)[:n]
    keys = rng.integers(0, n_keys, n).astype("float")
    keys[rng.random(n) < 0.1] = np.nan  # null keys
    return pl.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "event_time": T0 + (hours * 3_600_000_000).astype("timedelta64[us]"),
            "key": pl.Series(keys).fill_nan(None),
            "amt": rng.random(n) * 100,
        }
    )


def _brute(df, w, agg):
    rows = df.to_dicts()
    out = {}
    for r in rows:
        if r["key"] is None:
            continue
        lo = r["event_time"] - np.timedelta64(w, "D").astype("timedelta64[us]").item()
        vals = [
            x["amt"]
            for x in rows
            if x["key"] == r["key"] and lo <= x["event_time"] < r["event_time"]
        ]
        if not vals:
            out[r["event_id"]] = 0.0
        else:
            out[r["event_id"]] = {
                "count": len(vals),
                "sum": sum(vals),
                "mean": sum(vals) / len(vals),
                "max": max(vals),
                "min": min(vals),
            }[agg]
    return out


@pytest.mark.parametrize("with_ties", [True, False])
def test_rolling_matches_bruteforce(with_ties):
    df = _frame(with_ties=with_ties)
    aggs = ["count", "sum", "mean", "max", "min"]
    got = rolling(df, key="key", value="amt", windows_days=[7, 14], aggs=aggs, prefix="f")
    for w in (7, 14):
        for agg in aggs:
            exp = _brute(df, w, agg)
            col = dict(zip(got["event_id"], got[f"f_{agg}_{w}d"]))
            assert set(col) == set(exp)
            for k, v in exp.items():
                assert col[k] == pytest.approx(v), (w, agg, k)


def test_null_keys_absent_and_no_future_leakage():
    df = _frame()
    got = rolling(df, key="key", value="amt", windows_days=[30], aggs=["count"], prefix="f")
    assert got.height == df["key"].drop_nulls().len()
    # a row's own time is excluded: first event per key has count 0
    first = df.drop_nulls("key").sort("event_time").group_by("key").first()
    cnt = dict(zip(got["event_id"], got["f_count_30d"]))
    assert all(cnt[e] == 0 for e in first["event_id"])


def test_n_unique_and_unknown_agg():
    df = pl.DataFrame(
        {
            "event_id": ["a", "b", "c"],
            "event_time": T0
            + np.array([0, 1, 2], dtype="timedelta64[D]").astype("timedelta64[us]"),
            "device": [1, 1, 1],
            "user": [10, 11, 10],
        }
    )
    got = rolling(df, key="device", value="user", windows_days=[7], aggs=["n_unique"], prefix="d")
    assert got["d_n_unique_7d"].to_list() == [0, 1, 2]
    with pytest.raises(ValueError):
        rolling(df, key="device", value="user", windows_days=[7], aggs=["median"], prefix="d")
