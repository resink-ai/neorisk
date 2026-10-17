import numpy as np
import pytest

from neorisk_simkit import std
from neorisk_simkit.engine import Local
from neorisk_simkit.engine.rng import name_key
from neorisk_simkit.spec import dist
from neorisk_simkit.spec.plan import Column, TableDef
from neorisk_simkit.spec.types import amount, cat, i16


def test_reservation_fields_fit_a_local():
    f = std.reservations.fields(64)
    assert f == {"res_hold": "ref[64]", "res_item": "i32[64]", "res_qty": "i32[64]",
                 "res_ckt": "ref[64]"}
    assert Local(**f).fields["res_hold"] == ("ref", 64)
    with pytest.raises(ValueError, match="at least 2 slots"):
        std.reservations.fields(1)


def test_capped_pool_grants_whole_claims_only():
    take = std.capped_pool.take
    assert take(300, 100) == 100 and take(100, 100) == 100
    assert take(99, 100) == 0 and take(0, 1) == 0 and take(500, 0) == 0
    assert getattr(take, "py_func", take)(99, 100) == 0                        # same uncompiled
    assert std.capped_pool.init(300) == {"remaining": [300], "granted": [0]}
    with pytest.raises(ValueError, match="cap must be >= 0"):
        std.capped_pool.init(-1)


def test_capped_pool_never_grants_beyond_cap():
    for take in (std.capped_pool.take, getattr(std.capped_pool.take, "py_func", std.capped_pool.take)):
        remaining, granted = 1000, 0
        for amt in [400, 400, 201, 200, 1, 0, -5]:       # 201 is one more than is left
            g = take(remaining, amt)
            remaining -= g
            granted += g
        assert granted == 1000 and remaining == 0
        assert take(1000, 1001) == 0 and take(1000, 1000) == 1000


def test_catalog_hot_rows_are_group_zero():
    src = std.catalog(n=200, category=dist.categorical({"a": 1.0}),
                      price=dist.uniform_int(100, 200), group=dist.uniform_int(1, 7),
                      weight=dist.zipf(s=1.07), hot_rows=20)
    t = TableDef("sku", 0, "sku_id", (Column("category", cat("a")),
                                      Column("price", amount(asset="USD")),
                                      Column("sku_group", i16())), False, "", None, src, False)
    rows = src.generate(200, t, seed=3, stream=name_key("sku"))
    g = np.asarray(rows["sku_group"])
    assert (g[:20] == 0).all() and (g[20:] >= 1).all()
    with pytest.raises(ValueError, match=r"hot_rows must be in \[0, n\]"):
        std.catalog(n=5, category=dist.categorical({"a": 1.0}), price=dist.uniform_int(1, 2),
                    group=dist.uniform_int(0, 1), weight=dist.zipf(s=1.1), hot_rows=6)
