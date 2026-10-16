"""`std.rows`: explicit-row sources and their error paths."""

import pytest

from neorisk_simkit import std
from neorisk_simkit.spec.plan import Column, TableDef
from neorisk_simkit.spec.types import cat, i16


def _table(source):
    cols = (Column("sku_group", i16()), Column("label", cat("A", "B", "C")))
    return TableDef(name="sku", code=0, key="sku_id", cols=cols, mutable=False, doc="",
                    child_of=None, source=source, creatable=False)


def _gen(source):
    return source.generate(source.n, _table(source), seed=1, stream=0)


def test_rows_maps_labels_to_codes():
    out = _gen(std.rows(sku_group=[0, 1, 2], label=["C", "A", "B"]))
    assert out["sku_group"].tolist() == [0, 1, 2]
    assert out["label"].tolist() == [2, 0, 1]


def test_rows_rejects_unequal_lengths():
    with pytest.raises(ValueError, match="differ in length"):
        std.rows(sku_group=[0, 1], label=["A"])


def test_rows_rejects_missing_column():
    with pytest.raises(ValueError, match=r"table sku: .*no values for columns \['label'\]"):
        _gen(std.rows(sku_group=[0, 1]))


def test_rows_rejects_extra_column():
    src = std.rows(sku_group=[0], label=["A"], color=["red"])
    with pytest.raises(ValueError, match=r"table sku: .*unknown columns \['color'\]"):
        _gen(src)


def test_rows_rejects_unknown_label():
    with pytest.raises(ValueError, match="'D' is not a category"):
        _gen(std.rows(sku_group=[0], label=["D"]))
