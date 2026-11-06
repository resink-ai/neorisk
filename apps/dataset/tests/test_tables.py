import sqlite3

import pyarrow as pa
import pytest

from dataset.tables import (
    affinity,
    answer_table,
    column_types,
    compare_tables,
    detect_mixed,
    sqlite_table,
)


def _db(ddl: str, rows: list[tuple]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(ddl)
    if rows:
        ph = ", ".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO t VALUES ({ph})", rows)
    return con


@pytest.mark.parametrize(("decl", "want"), [
    ("INTEGER", "INTEGER"), ("BIGINT", "INTEGER"), ("INT2", "INTEGER"),
    ("VARCHAR(10)", "TEXT"), ("TEXT", "TEXT"), ("", "BLOB"), ("REAL", "REAL"),
    ("DOUBLE PRECISION", "REAL"), ("DECIMAL(10,2)", "NUMERIC"), ("NUMERIC", "NUMERIC"),
    ("DATE", "NUMERIC")])
def test_affinity_rules(decl, want):
    assert affinity(decl) == want


def test_mixed_column_becomes_sqlite_text():
    con = _db("CREATE TABLE t (c INTEGER)", [(274,), ("",), (None,), ("12a",)])
    assert detect_mixed(con, "t") == {"c"}
    got = sqlite_table(con, "t", {"c"})
    assert got.schema.field("c").type == pa.string()
    assert got.column("c").to_pylist() == ["274", "", None, "12a"]


def test_decimal_62_and_62_7_is_float_not_mixed():
    con = _db("CREATE TABLE t (c DECIMAL(10,2))", [(62,), (62.7,)])
    assert detect_mixed(con, "t") == set()
    assert column_types(con, "t") == {"c": "float64"}
    assert sqlite_table(con, "t", set()).column("c").to_pylist() == [62.0, 62.7]


def test_numeric_of_integers_stays_int64():
    con = _db("CREATE TABLE t (c NUMERIC)", [(2**62 + 1,), (None,)])
    assert column_types(con, "t") == {"c": "int64"}
    assert sqlite_table(con, "t", set()).column("c").to_pylist() == [2**62 + 1, None]


def test_int64_column_exact():
    con = _db("CREATE TABLE t (c INTEGER, s TEXT)", [(2**63 - 1, "x"), (-(2**63), None)])
    got = sqlite_table(con, "t", set())
    assert got.schema.field("c").type == pa.int64()
    assert got.column("c").to_pylist() == [2**63 - 1, -(2**63)]


def test_blob_value_refused():
    con = _db("CREATE TABLE t (c BLOB)", [(b"\x00\x01",)])
    with pytest.raises(ValueError, match="blob"):
        detect_mixed(con, "t")


def _t(**cols) -> pa.Table:
    return pa.table(cols)


def test_compare_int_equals_float():
    r = compare_tables("t", _t(a=pa.array([62], pa.int64())), _t(a=pa.array([62.0])))
    assert r.ok, r


def test_compare_null_empty_backslash_n_distinct():
    r = compare_tables("t", _t(a=pa.array([None, "", "\\N"], pa.string())),
                       _t(a=pa.array(["", "", "\\N"], pa.string())))
    assert not r.ok
    assert (r.missing, r.extra) == ([(None,)], [("",)])
    assert (r.rows_expected, r.rows_got) == (3, 3)


def test_float_tolerance_only_on_float_columns():
    assert compare_tables("t", _t(a=pa.array([1.0])), _t(a=pa.array([1.0 + 1e-12]))).ok
    assert not compare_tables("t", _t(a=pa.array([1.0])), _t(a=pa.array([1.001]))).ok
    assert not compare_tables("t", _t(a=pa.array(["1.0"])),
                              _t(a=pa.array(["1.0000000000001"]))).ok


def test_ordered_answer():
    e = _t(a=pa.array([1, 2], pa.int64()), b=pa.array(["x", "y"]))
    g = _t(a=pa.array([2, 1], pa.int64()), b=pa.array(["y", "x"]))
    assert compare_tables("q", e, g).ok
    assert not compare_tables("q", e, g, ordered=True).ok


def test_columns_must_match():
    r = compare_tables("t", _t(a=pa.array([1])), _t(a=pa.array([1]), extra=pa.array([2])))
    assert not r.ok and "extra" in r.detail


def test_columns_reordered_by_name():
    e = _t(a=pa.array([1]), b=pa.array(["x"]))
    assert compare_tables("t", e, _t(b=pa.array(["x"]), a=pa.array([1]))).ok


def test_answer_table_types():
    con = _db("CREATE TABLE t (i INTEGER, r REAL, s TEXT)", [(1, 1.5, "a"), (2, 2.0, None)])
    got = answer_table(con, "SELECT i, r, i + r AS x, s, NULL AS n, "
                            "CASE WHEN i = 1 THEN 'a' ELSE 2.5 END AS m FROM t ORDER BY i")
    types = {f.name: f.type for f in got.schema}
    assert types == {"i": pa.int64(), "r": pa.float64(), "x": pa.float64(), "s": pa.string(),
                     "n": pa.string(), "m": pa.string()}
    assert got.column("m").to_pylist() == ["a", "2.5"]
    assert got.column("i").to_pylist() == [1, 2]


def test_date_text_column_is_string_not_mixed():
    """A DATE column (NUMERIC affinity) holding only text is a text column, not mixed."""
    con = _db("CREATE TABLE t (d DATE, u)", [("1962-02-18 00:00:00", 1), (None, 2)])
    assert detect_mixed(con, "t") == set()
    assert column_types(con, "t") == {"d": "string", "u": "int64"}
    assert sqlite_table(con, "t", set()).column("d").to_pylist() == ["1962-02-18 00:00:00", None]


def test_compare_rejects_bool_and_decimal_columns():
    from decimal import Decimal
    e = _t(a=pa.array([1, 0], pa.int64()))
    r = compare_tables("t", e, _t(a=pa.array([True, False])))
    assert not r.ok and "bool" in r.detail
    r = compare_tables("t", _t(a=pa.array([1.5])),
                       _t(a=pa.array([Decimal("1.5")], pa.decimal128(5, 1))))
    assert not r.ok and "decimal" in r.detail
    assert compare_tables("t", _t(a=pa.array(["x"])), _t(a=pa.array(["x"], pa.large_string()))).ok
    assert compare_tables("t", e, _t(a=pa.array([1, 0], pa.int32()))).ok


def test_generated_column_in_results():
    con = _db("CREATE TABLE t (a INTEGER, b INTEGER GENERATED ALWAYS AS (a * 2) VIRTUAL)", [])
    con.execute("INSERT INTO t (a) VALUES (1), (5)")
    from dataset.tables import generated
    assert generated(con, "t") == {"b"}
    assert column_types(con, "t") == {"a": "int64", "b": "int64"}
    got = sqlite_table(con, "t", set())
    assert got.column_names == ["a", "b"]
    assert got.column("b").to_pylist() == [2, 10]


def test_exact_float_columns_compare_bit_for_bit():
    import math
    big = 9.0e18
    e = _t(a=pa.array([big, 0.5]))
    g = _t(a=pa.array([math.nextafter(big, math.inf), 0.5]))
    assert compare_tables("t", e, g).ok                     # within 1e-9: tolerated
    r = compare_tables("t", e, g, exact={"a"})
    assert not r.ok and r.missing == [(big,)]
    assert compare_tables("t", e, e, exact={"a"}).ok


def test_compare_extended_types():
    from datetime import UTC, date, datetime
    ts = pa.timestamp("us", tz="UTC")
    t = pa.table({"b": pa.array([True, False]), "d": pa.array([date(2026, 1, 1)] * 2),
                  "t": pa.array([datetime(2026, 1, 1, tzinfo=UTC)] * 2, ts)})
    assert compare_tables("x", t, t, extended=True).ok
    moved = t.set_column(2, "t", pa.array([datetime(2026, 1, 1, tzinfo=UTC),
                                           datetime(2026, 1, 2, tzinfo=UTC)], ts))
    assert not compare_tables("x", t, moved, extended=True).ok
    r = compare_tables("x", t, t)
    assert not r.ok and "outside the contract" in r.detail
