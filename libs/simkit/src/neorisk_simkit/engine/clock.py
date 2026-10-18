"""A monotonic nanosecond clock callable from compiled code (the shard-phase timer, D55, F-03).

`clock_ns()` reads the clock behind `time.perf_counter_ns()` with one C call compiled straight
into the caller: `clock_gettime_nsec_np(CLOCK_UPTIME_RAW)` (mach_absolute_time) on macOS,
`clock_gettime(CLOCK_MONOTONIC)` on Linux. The symbol is resolved by name when the module is
loaded, so a function that calls it caches like any other (`cache=True`), inlines, and holds no
GIL (~10 ns a call). Uncompiled (`NUMBA_DISABLE_JIT=1`) it is `time.perf_counter_ns` itself,
since an intrinsic cannot run as Python. It replaces an `objmode` call to `time.perf_counter_ns`, which must take the
GIL each time and slowed the S1 reduced profile's compiled rounds by about 6% (Task 19 report).
"""

from __future__ import annotations

import sys
import time

from llvmlite import ir
from numba import config, types
from numba.core import cgutils
from numba.core.errors import TypingError
from numba.extending import intrinsic

_CLOCK_UPTIME_RAW = 8          # macOS <time.h>; the clock of mach_absolute_time / perf_counter
_CLOCK_MONOTONIC = 1           # Linux <time.h>; the clock of perf_counter
_NS = 1_000_000_000


@intrinsic
def clock_ns(typingctx):
    """int64 nanoseconds of the monotonic clock `time.perf_counter_ns()` reads."""
    if sys.platform not in ("darwin", "linux"):
        raise TypingError(f"clock_ns: no compiled clock for platform {sys.platform}")

    def codegen(context, builder, signature, args):
        i32, i64 = ir.IntType(32), ir.IntType(64)
        if sys.platform == "darwin":
            fn = cgutils.get_or_insert_function(builder.module, ir.FunctionType(i64, [i32]),
                                                "clock_gettime_nsec_np")
            return builder.call(fn, [ir.Constant(i32, _CLOCK_UPTIME_RAW)])
        timespec = ir.LiteralStructType([i64, i64])          # (tv_sec, tv_nsec), LP64
        ts = cgutils.alloca_once(builder, timespec)
        fn = cgutils.get_or_insert_function(
            builder.module, ir.FunctionType(i32, [i32, timespec.as_pointer()]), "clock_gettime")
        builder.call(fn, [ir.Constant(i32, _CLOCK_MONOTONIC), ts])
        sec = builder.load(cgutils.gep_inbounds(builder, ts, 0, 0))
        nsec = builder.load(cgutils.gep_inbounds(builder, ts, 0, 1))
        return builder.add(builder.mul(sec, ir.Constant(i64, _NS)), nsec)

    return types.int64(), codegen


if config.DISABLE_JIT:                      # uncompiled runs (D3): an intrinsic is not callable
    clock_ns = time.perf_counter_ns
