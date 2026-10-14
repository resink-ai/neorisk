import numpy as np
import polars as pl
import pytest

from neorisk_simkit.features import rolling, rolling_asof

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
            "u": pl.Series(np.where(rng.random(n) < 0.2, -1, rng.integers(0, 5, n))).replace(
                -1, None
            ),
        }
    )


def _brute(df, w, agg, value="amt"):
    rows = df.to_dicts()
    out = {}
    for r in rows:
        if r["key"] is None:
            continue
        lo = r["event_time"] - np.timedelta64(w, "D").astype("timedelta64[us]").item()
        vals = [
            x[value]
            for x in rows
            if x["key"] == r["key"] and lo <= x["event_time"] < r["event_time"]
        ]
        if agg == "n_unique":
            vals = [v for v in vals if v is not None]  # n_unique ignores nulls
        if not vals:
            out[r["event_id"]] = 0.0
        else:
            out[r["event_id"]] = {
                "count": len(vals),
                "sum": sum(vals),
                "mean": sum(vals) / len(vals),
                "max": max(vals),
                "min": min(vals),
                "n_unique": len(set(vals)),
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
    got_u = rolling(df, key="key", value="u", windows_days=[7, 14], aggs=["n_unique"], prefix="g")
    for w in (7, 14):
        exp = _brute(df, w, "n_unique", value="u")
        col = dict(zip(got_u["event_id"], got_u[f"g_n_unique_{w}d"]))
        assert set(col) == set(exp)
        assert all(col[k] == v for k, v in exp.items()), w


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


def test_tied_rows_are_excluded_from_each_others_window():
    t = T0 + np.array([0, 24, 24, 48], dtype="timedelta64[h]").astype("timedelta64[us]")
    df = pl.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "event_time": t,
            "key": [1] * 4,
            "amt": [1.0, 2.0, 4.0, 8.0],
        }
    )
    got = rolling(df, key="key", value="amt", windows_days=[7], aggs=["count", "sum"], prefix="f")
    res = dict(zip(got["event_id"], zip(got["f_count_7d"], got["f_sum_7d"])))
    assert res == {"a": (0, 0.0), "b": (1, 1.0), "c": (1, 1.0), "d": (3, 7.0)}


def test_output_is_ordered_by_key_then_time():
    df = _frame()
    got = rolling(df, key="key", value="amt", windows_days=[7], aggs=["count"], prefix="f")
    order = df.drop_nulls("key").sort(["key", "event_time"], maintain_order=True)["event_id"]
    assert got["event_id"].equals(order)


def test_empty_and_non_empty_outputs_have_same_dtypes():
    aggs = ["count", "sum", "mean", "max", "min", "n_unique"]
    df = _frame()
    full = rolling(df, key="key", value="u", windows_days=[7], aggs=aggs, prefix="f")
    empty = rolling(df.head(0), key="key", value="u", windows_days=[7], aggs=aggs, prefix="f")
    assert empty.height == 0 and empty.schema == full.schema
    for a in aggs:
        dt = full.schema[f"f_{a}_7d"]
        assert dt == (pl.Int64 if a in ("count", "n_unique") else pl.Float64), a


def _asof_frames(seed=0):
    rng = np.random.default_rng(seed)
    nq, ns = 400, 150
    q_hours = rng.integers(0, 24 * 40, nq)
    s_hours = np.concatenate([rng.integers(0, 24 * 40, ns - 20), q_hours[:20]])  # ties
    qk = rng.integers(0, 6, nq).astype("float")
    qk[rng.random(nq) < 0.1] = np.nan
    sk = rng.integers(0, 6, ns).astype("float")
    sk[rng.random(ns) < 0.1] = np.nan
    us = 3_600_000_000
    queries = pl.DataFrame(
        {
            "event_id": [f"q{i}" for i in range(nq)],
            "event_time": T0 + (q_hours * us).astype("timedelta64[us]"),
            "user": pl.Series(qk).fill_nan(None).cast(pl.Int64),
        }
    )
    source = pl.DataFrame(
        {
            "event_time": T0 + (s_hours * us).astype("timedelta64[us]"),
            "inviter": pl.Series(sk).fill_nan(None).cast(pl.Int64),
            "bonus": rng.integers(1, 100, ns),
        }
    )
    return queries, source


def test_rolling_asof_matches_bruteforce_and_keeps_query_order():
    queries, source = _asof_frames()
    aggs = ["count", "sum", "mean", "max"]
    got = rolling_asof(
        queries,
        source,
        query_key="user",
        source_key="inviter",
        value="bonus",
        windows_days=[7, 30],
        aggs=aggs,
        prefix="r",
    )
    assert got["event_id"].equals(queries["event_id"])
    src = source.to_dicts()
    for q, row in zip(queries.to_dicts(), got.to_dicts()):
        for w in (7, 30):
            lo = q["event_time"] - np.timedelta64(w, "D").astype("timedelta64[us]").item()
            vals = [
                s["bonus"]
                for s in src
                if q["user"] is not None
                and s["inviter"] == q["user"]
                and lo <= s["event_time"] < q["event_time"]
            ]
            exp = {
                "count": len(vals),
                "sum": sum(vals),
                "mean": sum(vals) / len(vals) if vals else 0.0,
                "max": max(vals) if vals else 0.0,
            }
            for a in aggs:
                assert row[f"r_{a}_{w}d"] == pytest.approx(exp[a]), (q["event_id"], a, w)


def test_rolling_asof_excludes_same_instant_source_rows():
    t = T0 + np.array([0, 24], dtype="timedelta64[h]").astype("timedelta64[us]")
    queries = pl.DataFrame({"event_id": ["a", "b"], "event_time": t, "user": [1, 1]})
    source = pl.DataFrame({"event_time": t[:1], "inviter": [1], "bonus": [5]})
    got = rolling_asof(
        queries,
        source,
        query_key="user",
        source_key="inviter",
        value="bonus",
        windows_days=[7],
        aggs=["count"],
        prefix="r",
    )
    assert got["r_count_7d"].to_list() == [0, 1]
    assert got.schema["r_count_7d"] == pl.Int64
