"""A monotonic nanosecond clock callable from compiled code (the shard-phase timer, D55, F-03).

`clock_ns()` reads the clock behind `time.perf_counter_ns()` with one C call compiled straight
into the caller: `clock_gettime_nsec_np(CLOCK_UPTIME_RAW)` (mach_absolute_time) on macOS,
`clock_gettime(CLOCK_MONOTONIC)` on Linux. The symbol is resolved by name when the module is
loaded, so a function that calls it caches like any other (`cache=True`), inlines, and holds no
GIL (~10 ns a call). On any other platform it compiles to the constant 0: the compiled engine
still builds and runs, but compiled shard phases go untimed, so `compiled_clock_available()`
is False and the run reports its shard timing as unavailable (`run_stats.json`
`shard_events_per_second = null`, `shard_timing` says why); the benchmark's shard-phase gate
is then "not measured", never a pass. Uncompiled (`NUMBA_DISABLE_JIT=1`) it is `time.perf_counter_ns`
itself, since an intrinsic cannot run as Python. It replaces an `objmode` call to
`time.perf_counter_ns`, which must take the GIL each time and slowed the S1 reduced profile's
compiled rounds by about 6% (Task 19 report).
"""

from __future__ import annotations

import sys
import time

from llvmlite import ir
from numba import config, types
from numba.core import cgutils
from numba.extending import intrinsic

_CLOCK_UPTIME_RAW = 8          # macOS <time.h>; the clock of mach_absolute_time / perf_counter
_CLOCK_MONOTONIC = 1           # Linux <time.h>; the clock of perf_counter
_NS = 1_000_000_000


def clock_source(platform: str) -> str | None:
    """The C function `clock_ns` calls on `platform` (a `sys.platform` value), or None: no
    compiled clock there, so `clock_ns` compiles to the constant 0."""
    return {"darwin": "clock_gettime_nsec_np", "linux": "clock_gettime"}.get(platform)


def clock_ir(builder: ir.IRBuilder, source: str | None) -> ir.Value:
    """Emit the clock read for `clock_source(...)` = `source` at `builder`: an i64 value."""
    i32, i64 = ir.IntType(32), ir.IntType(64)
    if source is None:
        return ir.Constant(i64, 0)
    if source == "clock_gettime_nsec_np":
        fn = cgutils.get_or_insert_function(builder.module, ir.FunctionType(i64, [i32]), source)
        return builder.call(fn, [ir.Constant(i32, _CLOCK_UPTIME_RAW)])
    timespec = ir.LiteralStructType([i64, i64])              # (tv_sec, tv_nsec), LP64
    ts = cgutils.alloca_once(builder, timespec)
    fn = cgutils.get_or_insert_function(
        builder.module, ir.FunctionType(i32, [i32, timespec.as_pointer()]), source)
    builder.call(fn, [ir.Constant(i32, _CLOCK_MONOTONIC), ts])
    sec = builder.load(cgutils.gep_inbounds(builder, ts, 0, 0))
    nsec = builder.load(cgutils.gep_inbounds(builder, ts, 0, 1))
    return builder.add(builder.mul(sec, ir.Constant(i64, _NS)), nsec)


def compiled_clock_available() -> bool:
    """Whether `clock_ns` reads a real clock here: compiled with a C clock for this platform,
    or uncompiled (`time.perf_counter_ns`)."""
    return bool(config.DISABLE_JIT) or clock_source(sys.platform) is not None


@intrinsic
def clock_ns(typingctx):
    """int64 nanoseconds of the monotonic clock `time.perf_counter_ns()` reads (0 on a platform
    without a compiled clock, see `clock_source`)."""
    source = clock_source(sys.platform)

    def codegen(context, builder, signature, args):
        return clock_ir(builder, source)

    return types.int64(), codegen


if config.DISABLE_JIT:                      # uncompiled runs (D3): an intrinsic is not callable
    clock_ns = time.perf_counter_ns
