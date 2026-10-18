"""Checked int64 arithmetic: identical results compiled and uncompiled (no wrap-around).

Operands are widened to int64 first. Compiled, Numba already computes narrower ints in int64;
uncompiled (`NUMBA_DISABLE_JIT`), NumPy 2 would keep a narrow operand's type, so a bound such as
`I64_MAX // b` with an int16 `b` raised `OverflowError` on a product that fits.
"""

import numpy as np
from numba import njit

I64_MAX = 9_223_372_036_854_775_807
I64_MIN = -9_223_372_036_854_775_808
NULL = I64_MIN


@njit(cache=True)
def checked_add(a, b):
    a, b = np.int64(a), np.int64(b)
    if b > 0 and a > I64_MAX - b:
        raise OverflowError("int64 overflow")
    if b < 0 and a < I64_MIN - b:
        raise OverflowError("int64 overflow")
    return a + b


@njit(cache=True)
def checked_sub(a, b):
    a, b = np.int64(a), np.int64(b)
    if b < 0 and a > I64_MAX + b:
        raise OverflowError("int64 overflow")
    if b > 0 and a < I64_MIN + b:
        raise OverflowError("int64 overflow")
    return a - b


@njit(cache=True)
def checked_mul(a, b):
    a, b = np.int64(a), np.int64(b)
    if a == 0 or b == 0:
        return 0
    if (a > 0) != (b > 0):
        # Mixed signs: product is negative; require it >= I64_MIN.
        p = a if a > 0 else b  # positive factor
        n = b if a > 0 else a  # negative factor
        lim = I64_MIN // p
        if I64_MIN % p != 0:
            lim += 1  # ceil(I64_MIN / p)
        if n < lim:
            raise OverflowError("int64 overflow")
    elif a > 0:
        if a > I64_MAX // b:
            raise OverflowError("int64 overflow")
    else:
        # Both negative: product positive; I64_MIN as a factor always overflows.
        if a == I64_MIN or b == I64_MIN or -a > I64_MAX // (-b):
            raise OverflowError("int64 overflow")
    return a * b


@njit(cache=True)
def checked_min(a, b):
    return min(b, a)


@njit(cache=True)
def checked_max(a, b):
    return max(b, a)
