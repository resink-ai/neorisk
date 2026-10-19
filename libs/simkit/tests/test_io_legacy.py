"""Legacy adapter pieces on hand-built frames (Task 20 review M3, M4, M6): role codes across
labels tables, the as-of user state at a move's very instant, equal-time rolling windows."""

from datetime import datetime, timedelta

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from neorisk_simkit.io import legacy

T0 = datetime(2026, 1, 1)


def _t(s):
    return T0 + timedelta(seconds=s)


def test_a_move_applies_when_it_precedes_the_row_in_canonical_order():
    # user 1 moves at t=10 with lamport 4 (before its row at lamport 5: applies) and again at
    # t=10 with lamport 6 (after it: does not); a time-only as-of would take either
    rows = pl.DataFrame({"user_id": [1, 1, 2], "event_time": [_t(10), _t(20), _t(10)],
                         "lamport": [5, 9, 5], "partition_id": [7, 7, 8], "seq": [0, 0, 0],
                         "x": ["a", "b", "c"]})
    moves = pl.DataFrame({"user_id": [1, 1], "event_time": [_t(10), _t(10)],
                          "lamport": [4, 6], "partition_id": [7, 7], "seq": [1, 1],
                          "_state": [11, 12]})
    out = legacy._state_as_of(rows, moves)
    assert out.select("x", "_state").rows() == [("a", 11), ("b", 12), ("c", None)]
    assert out.columns == [*rows.columns, "_state"]


def _labels(run_dir, name, rows):
    f = run_dir / "labels" / name / "date=2026-01-01" / "step-000000.parquet"
    f.parent.mkdir(parents=True)
    n = len(rows)
    pq.write_table(pa.table({
        "target_id": pa.array([r[0] for r in rows], pa.int64()),
        "event_time": pa.array([_t(0)] * n, pa.timestamp("us")),
        "lamport": pa.array(range(n), pa.int64()), "partition_id": pa.array([1] * n, pa.int64()),
        "seq": pa.array([0] * n, pa.int64()),
        "final_label": pa.array([True] * n), "role": pa.array([r[1] for r in rows])}), f)


def test_role_codes_never_collide_across_labels_tables(tmp_path):
    def table(name, roles):
        return {"name": name, "kind": "label",
                "columns": [{"name": "role", "values": list(roles)}]}

    sc = legacy._Schema({"tables": [table("labels_a", ("hunter", "zombie")),
                                    table("labels_b", ("boss", "minion"))]})
    _labels(tmp_path, "labels_a", [(1, "hunter"), (2, "zombie")])
    _labels(tmp_path, "labels_b", [(3, "boss"), (4, "minion")])
    t = legacy._targets(tmp_path, sc).sort("target_id")
    assert t["actor_role"].to_list() == [1, 2, 3, 4]
    assert t["zombie"].to_list() == [False, True, False, False]


def test_rolling_features_exclude_rows_at_the_same_instant():
    # two orders of user 1 at one instant see neither each other; the later one sees both
    ev = pl.DataFrame({
        "event_id": ["o:1", "o:2", "o:3"], "event_time": [_t(0), _t(0), _t(60)],
        "event_type": [0, 0, 0], "user_id": [1, 1, 1], "device_id": [5, 5, 5],
        "inviter_id": pl.Series([None] * 3, dtype=pl.Int64), "amount": [10.0, 20.0, 30.0],
        "referral_bonus": pl.Series([None] * 3, dtype=pl.Float64),
        "invitee_is_zombie": [0, 0, 0], "actor_role": [0, 0, 0], "label": [0, 0, 0]})
    g = legacy._golden(ev)
    assert g["u_amt_count_7d"].to_list() == [0, 0, 2]
    assert g["u_amt_sum_7d"].to_list() == [0.0, 0.0, 30.0]
    assert g["dev_users_n_unique_7d"].to_list() == [0, 0, 1]
