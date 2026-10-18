import numba
import pytest

from neorisk_simkit import std
from neorisk_simkit.engine import (
    COMMIT,
    PRIO_CONTINUE,
    PRIO_EXPIRY,
    PRIO_MESSAGE,
    PRIO_TIMER,
    RETRY,
    START,
    CapExceeded,
    KernelSpec,
    Local,
    Res,
    kernel,
    reject,
)


def test_codes_and_priorities():
    assert COMMIT == 0 and RETRY == -1 and START == 0
    assert reject(0) == 1 and reject(7) == 8
    assert PRIO_CONTINUE < PRIO_MESSAGE < PRIO_EXPIRY < PRIO_TIMER


def test_kernel_decorator_records_spec():
    @kernel(state="user", local=Local(n="i16", cart="i32[5]", h="ref"), commands=(1, 2),
            max=Res(records={"a": 1}, creates={"order": 1}, timers=2, requests=3))
    def k(ctx, s, loc, cmd, out):
        return COMMIT

    spec = k.__kernel__
    assert isinstance(spec, KernelSpec)
    assert spec.name == "k" and spec.state == "user" and spec.commands == (1, 2)
    assert dict(spec.max.records) == {"a": 1} and dict(spec.max.creates) == {"order": 1}
    assert spec.max.timers == 2 and spec.max.requests == 3
    assert spec.local.fields == {"n": ("i16", 1), "cart": ("i32", 5), "h": ("ref", 1)}
    assert spec.params == ("ctx", "s", "loc", "cmd", "out")
    assert spec.module_file.endswith("test_engine_abi.py")
    assert k(None, None, None, None, None) == COMMIT


def test_kernel_signature_is_checked():
    with pytest.raises(TypeError, match="ctx, s, loc, cmd, out"):
        @kernel(state="user", local=Local(n="i16"))
        def bad(ctx, s, cmd, out):
            return COMMIT
    with pytest.raises(TypeError, match="ctx, s, cmd, out"):
        @kernel(state="user")
        def bad2(ctx, s, loc, cmd, out):
            return COMMIT


def test_local_and_res_validation():
    with pytest.raises(ValueError, match="unknown local type"):
        Local(x="str")
    with pytest.raises(ValueError, match="must be >= 0"):
        Res(timers=-1)
    with pytest.raises(ValueError, match="must be >= 0"):
        Res(records={"a": -2})
    with pytest.raises(ValueError, match="substep"):
        kernel(state="bin", substep=0)


def test_command_ids_must_not_use_start_twice():
    with pytest.raises(ValueError, match="duplicate command"):
        kernel(state="user", commands=(START, 1, 1))


def test_checked_arithmetic_python():
    assert std.checked_add(2, 3) == 5
    assert std.checked_sub(2, 3) == -1
    assert std.checked_min(3, 2) == 2 and std.checked_max(3, 2) == 3
    assert std.checked_mul(-4, 5) == -20
    with pytest.raises(OverflowError):
        std.checked_add(2**63 - 1, 1)
    with pytest.raises(OverflowError):
        std.checked_sub(-(2**63), 1)
    with pytest.raises(OverflowError):
        std.checked_mul(2**62, 2)


def test_checked_arithmetic_compiled_matches():
    add = numba.njit(lambda a, b: std.checked_add(a, b))
    mul = numba.njit(lambda a, b: std.checked_mul(a, b))
    assert add(2, 3) == 5 and mul(6, 7) == 42
    with pytest.raises(OverflowError):
        add(2**63 - 1, 1)
    with pytest.raises(OverflowError):
        mul(2**62, 2)
    assert std.NULL == -(2**63)


def test_checked_arithmetic_widens_narrow_ints_uncompiled():
    """Task 15 (a): uncompiled (`NUMBA_DISABLE_JIT`, here `py_func`) a narrow operand is
    widened to int64 first, as compiled code does; NumPy 2 kept it narrow and raised on
    `I64_MAX // b` for a product that fits."""
    import numpy as np

    a, b = np.int64(2**40), np.int16(30_000)
    mul = numba.njit(lambda x, y: std.checked_mul(x, y))
    assert std.checked_mul.py_func(a, b) == mul(a, b) == 2**40 * 30_000
    assert std.checked_mul.py_func(np.int16(-3), a) == mul(np.int16(-3), a) == -3 * 2**40
    assert std.checked_add.py_func(np.int8(5), np.int64(2**62)) == 5 + 2**62
    assert std.checked_sub.py_func(np.int16(-7), np.int64(2**62)) == -7 - 2**62
    for f, x, y in ((std.checked_mul, np.int64(2**62), np.int16(4)),
                    (std.checked_add, np.int64(2**63 - 1), np.int8(1)),
                    (std.checked_sub, np.int64(-(2**63)), np.int16(1))):
        with pytest.raises(OverflowError, match="int64 overflow"):
            f.py_func(x, y)


def test_cap_exceeded_message():
    e = CapExceeded("timer_heaps", 10, 11)
    assert e.item == "timer_heaps" and "timer_heaps" in str(e) and "limit 10" in str(e)
    a = CapExceeded("max_admissions_per_step", 0, 1, process="journey")
    assert a.item == "max_admissions_per_step" and a.process == "journey"
    assert str(a).endswith("in process journey") and e.process is None
