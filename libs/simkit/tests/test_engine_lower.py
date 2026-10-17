import textwrap

import numpy as np
import pytest

from neorisk_simkit.engine.layout import kernel_layouts
from neorisk_simkit.engine.lower import LoweringError, lower_module
from neorisk_simkit.spec.project import load_project, resolve_run

STD_NULL = -(2**63)


@pytest.fixture
def plan(fixture_project):
    return resolve_run(load_project(fixture_project("mini")), "sample", []).plan


def _lower(plan, body, proc="user_main"):
    src = textwrap.dedent(body)
    return lower_module(src, kernel_layouts(plan), {"k": proc})


def _exec(lowered, **stubs):
    ns = dict(stubs)
    exec(compile(lowered, "<lowered>", "exec"), ns)  # noqa: S102 - running lowered code is the test
    return ns


class Rec:
    def __init__(self, ret=None):
        self.calls, self.ret = [], ret

    def __call__(self, *args):
        self.calls.append(args)
        return self.ret


def _ctx(t=1000, self_id=3):
    cfg = ((1, 3.6e9, 0.0, 0.0), 0.3, 0.2, 50)
    return (t, self_id, 99, 0, 0, 0, 0, np.zeros(33, np.int64), 7, cfg, (), (), 1, 0)


def test_emit_maps_kwargs_to_column_order_and_cat_codes(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            out.emit_took(ctx.t, ok="no", item_id=5, user_id=ctx.self_id)
            return 0
    """)
    emit = Rec()
    ns = _exec(low, _emit_took=emit)
    c = _ctx()                      # one ctx object: tuple == short-circuits on identity
    ns["k"](c, None, None, None, "OUT")
    assert emit.calls == [("OUT", c, 1000, 3, 5, 1)]


def test_missing_optional_becomes_null_and_missing_required_fails(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            out.emit_ping(ctx.t, user_id=1, visit_id=2, n=3)
            return 0
    """)
    emit = Rec()
    ns = _exec(low, _emit_ping=emit)
    ns["k"](_ctx(), None, None, None, "OUT")
    assert emit.calls[0][-1] == STD_NULL
    with pytest.raises(LoweringError, match="missing required column 'n'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                out.emit_ping(ctx.t, user_id=1, visit_id=2)
                return 0
        """)
    with pytest.raises(LoweringError, match="unknown column 'zzz'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                out.emit_ping(ctx.t, user_id=1, visit_id=2, n=1, zzz=1)
                return 0
        """)


def test_state_and_local_access_reads_and_writes_arrays(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            s.balance = s.balance + 5
            loc.pings += 1
            if s.tier == "b":
                return 1
            return 0
    """)
    ns = _exec(low)
    tier, balance, last_note = (np.array([0, 1], np.int16), np.array([10, 20], np.int64),
                                np.array([STD_NULL] * 2, np.int64))
    s = (1, tier, balance, last_note)
    loc = (1, np.array([0, 4], np.int32), np.zeros(2, np.int64))
    assert ns["k"](_ctx(), s, loc, None, None) == 1
    assert balance.tolist() == [10, 25] and loc[1].tolist() == [0, 5]


def test_cfg_alias_and_rng_calls(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            cfg = ctx.cfg
            if ctx.rng.bernoulli(site=2, p=cfg.take_p):
                return ctx.rng.dist_us(site=1, d=cfg.ping_gap)
            return 0
    """)
    bern, dus = Rec(True), Rec(77)
    ns = _exec(low, _rng_bernoulli=bern, _rng_dist_us=dus)
    assert ns["k"](_ctx(), None, None, None, None) == 77
    assert bern.calls[0][1:] == (2, 0.3) and dus.calls[0][1:] == (1, (1, 3.6e9, 0.0, 0.0))


def test_site_rules(plan):
    with pytest.raises(LoweringError, match="site 2 used twice in user_main"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                a = ctx.rng.uniform(site=2)
                b = ctx.rng.uniform(site=2)
                return 0
        """)
    with pytest.raises(LoweringError, match="site= must be an int literal"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                return ctx.rng.uniform()
        """)


def test_reserve_builds_full_vector(plan):
    low = _lower(plan, """
        def k(ctx, s, loc, cmd, out):
            if not out.reserve(records={"ping": 1}, creates={"visit": 1}, timers=1, requests=1):
                return -1
            return 0
    """)
    res = Rec(True)
    ns = _exec(low, _reserve_user_main=res)
    ns["k"](_ctx(), None, None, None, "OUT")
    vec = res.calls[0][1]
    # resources: 5 events, 0 change groups, 2 namespaces, timers, outbox
    assert vec == (0, 1, 0, 0, 0, 0, 1, 1, 1)


def test_mutable_global_and_unknown_out_method_are_rejected(plan):
    with pytest.raises(LoweringError, match="mutable module global 'CACHE'"):
        _lower(plan, """
            CACHE = []
            def k(ctx, s, loc, cmd, out):
                return len(CACHE)
        """)
    with pytest.raises(LoweringError, match="unknown out method 'frobnicate'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                out.frobnicate()
                return 0
        """)


def test_payload_and_shard_views(plan):
    low = _lower(plan, """
        def k(ctx, s, cmd, out):
            i = cmd.item_id
            s.on_hand[i] -= 1
            return s.n_item + s.item[i]
    """, proc="bin_desk")
    ns = _exec(low)
    pay = np.zeros((4, 12), np.int64)
    pay[2, 0] = 1
    cmd = (1, 0, 0, 0, 0, pay, 2)
    on_hand = np.array([5, 5, 5, 5], np.int32)
    s = (1, 2, 2, np.array([10, 11, 12, 13], np.int64), on_hand)
    assert ns["k"](_ctx(), s, cmd, None) == 2 + 13
    assert on_hand.tolist() == [5, 5, 5, 4]


def test_lowering_the_real_mini_kernels(plan):
    from pathlib import Path
    src = Path(plan.process("user_main").kernel.module_file).read_text()
    low = lower_module(src, kernel_layouts(plan), {"user_main": "user_main", "bin_desk": "bin_desk"})
    compile(low, "<mini>", "exec")
    assert "_emit_ping(" in low and "_respond_take_ok(" in low and "@kernel" not in low


# ---------------------------------------------------------------- fix round 1 regressions


def test_str_literal_against_non_category_expression_is_rejected(plan):
    with pytest.raises(LoweringError, match="string literal compared with a non-category"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                x = s.tier
                return x == "b"
        """)
    with pytest.raises(LoweringError, match="string literal assigned to"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                s.balance = "b"
                return 0
        """)


def test_payload_slots_must_fit_the_user_columns_of_the_arena():
    from neorisk_simkit.engine import layout
    from neorisk_simkit.spec.plan import Column
    from neorisk_simkit.spec.types import i64

    cols = tuple(Column(f"p{i}", i64()) for i in range(layout.PAYLOAD_USER_COLS + 1))
    with pytest.raises(LoweringError, match="payload 'p7' needs slot 7"):
        layout._add_slots({}, cols, "boundary wide")


def test_array_local_needs_at_least_two_slots():
    from neorisk_simkit.engine import Local

    with pytest.raises(ValueError, match="at least 2"):
        Local(x="i32[1]")


def test_reserve_rejects_duplicate_keys(plan):
    with pytest.raises(LoweringError, match="duplicate key 'ping'"):
        _lower(plan, """
            def k(ctx, s, loc, cmd, out):
                return out.reserve(records={"ping": 1, "ping": 2})
        """)


def test_row_count_of_a_table_without_fixed_n_is_read_at_runtime(plan):
    import dataclasses

    lay = kernel_layouts(plan)
    lay["user_main"] = dataclasses.replace(lay["user_main"], read_n={"item": None})
    low = lower_module(textwrap.dedent("""
        def k(ctx, s, loc, cmd, out):
            return ctx.reads.item.n
    """), lay, {"k": "user_main"})
    assert "ctx[10][0].shape[0]" in low
    reads = (np.zeros(17, np.int32), np.zeros(17, np.int64), np.zeros(17, np.int32))
    c = _ctx()
    c = c[:10] + (reads,) + c[11:]
    assert _exec(low)["k"](c, None, None, None, None) == 17


def test_lowering_is_byte_identical_on_repeat(plan):
    from pathlib import Path
    src = Path(plan.process("user_main").kernel.module_file).read_text()
    funcs = {"user_main": "user_main", "bin_desk": "bin_desk"}
    a = lower_module(src, kernel_layouts(plan), funcs)
    b = lower_module(src, kernel_layouts(plan), funcs)
    assert a == b


@pytest.mark.parametrize("body, cycle", [
    ("""
        def fact(n):
            return 1 if n <= 1 else n * fact(n - 1)

        def k(ctx, s, loc, cmd, out):
            return fact(3)
    """, "fact -> fact"),
    ("""
        def even(n):
            return True if n == 0 else odd(n - 1)

        def odd(n):
            return False if n == 0 else even(n - 1)

        def k(ctx, s, loc, cmd, out):
            return even(4)
    """, "even -> odd -> even"),
], ids=["self", "mutual"])
def test_recursive_helpers_are_rejected(plan, body, cycle):
    """Helpers are compiled `inline='always'`, so recursion cannot compile; lowering says so
    instead of an opaque Numba error."""
    with pytest.raises(LoweringError, match=f"recursive.*{cycle}"):
        _lower(plan, body)
