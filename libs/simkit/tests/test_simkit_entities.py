import numpy as np
import polars as pl

from neorisk_simkit.attributes import AttrSpec, Cardinality, Volatility
from neorisk_simkit.entities import (
    EntitySpec,
    EntityTable,
    attach_asof,
    build_entities,
    map_ids,
)

T0 = np.datetime64("2026-01-01T00:00:00", "us")
T1 = T0 + np.timedelta64(90, "D")


def _dt(x: np.datetime64):
    # polars 2.x cannot build a column from np.datetime64 scalars; use python datetimes
    return x.astype("datetime64[us]").item()


def test_build_entities_shape_and_order():
    spec = EntitySpec(
        "user",
        200,
        (
            AttrSpec("state", Cardinality.LOW, Volatility.SLOW, k=50),
            AttrSpec("street", Cardinality.HIGH, Volatility.SLOW),
        ),
        created_frac=0.5,
    )
    t = build_entities(spec, T0, T1, np.random.default_rng(0))
    created = t.created_at()
    assert t.n == 200 and (np.diff(created.astype("int64")) >= 0).all()
    assert created.max() < T0 + np.timedelta64(45, "D")
    assert t.ids["entity_id"].n_unique() == 200
    assert set(t.attrs["attr"].unique()) == {"state", "street"}


def test_entities_differ_across_ids_for_slow_attr():
    spec = EntitySpec("user", 300, (AttrSpec("street", Cardinality.HIGH, Volatility.SLOW),))
    t = build_entities(spec, T0, T1, np.random.default_rng(1))
    first = t.attrs.sort("idx", "valid_from").group_by("idx", maintain_order=True).first()
    assert first["value"].n_unique() > 290


def _manual_table():
    ids = pl.DataFrame(
        {"idx": [0], "entity_id": ["u0"], "created_at": [_dt(T0)]},
        schema={"idx": pl.Int64, "entity_id": pl.Utf8, "created_at": pl.Datetime("us")},
    )
    attrs = pl.DataFrame(
        {
            "idx": [0, 0],
            "attr": ["state", "state"],
            "valid_from": [_dt(T0), _dt(T0 + np.timedelta64(10, "D"))],
            "value": [5, 7],
        }
    )
    return EntityTable("user", ids, attrs)


def test_attach_asof_picks_latest_valid_value_and_preserves_order():
    ev = pl.DataFrame(
        {
            "user_idx": [0, 0, 0],
            "event_time": [
                _dt(T0 + np.timedelta64(11, "D")),
                _dt(T0 + np.timedelta64(1, "D")),
                _dt(T0 + np.timedelta64(10, "D")),
            ],
        }
    )
    out = attach_asof(ev, _manual_table(), idx_col="user_idx")
    assert out["user_state"].to_list() == [7, 5, 7]


def test_attach_asof_null_idx_gives_null_attrs():
    ev = pl.DataFrame(
        {"user_idx": [0, None], "event_time": [_dt(T0 + np.timedelta64(1, "D"))] * 2},
        schema={"user_idx": pl.Int64, "event_time": pl.Datetime("us")},
    )
    out = attach_asof(ev, _manual_table(), idx_col="user_idx")
    assert out["user_state"].to_list() == [5, None]


def test_map_ids_handles_nulls():
    s = map_ids(_manual_table(), pl.Series("x", [0, None], dtype=pl.Int64))
    assert s.to_list() == ["u0", None]
