"""Simulation engine: kernel ABI surface (execution machinery arrives in later tasks)."""

from neorisk_simkit.engine.abi import (
    COMMIT,
    PRIO_CONTINUE,
    PRIO_EXPIRY,
    PRIO_MESSAGE,
    PRIO_TIMER,
    RETRY,
    START,
    ActionRef,
    ActionSpec,
    KernelSpec,
    Local,
    Res,
    action,
    kernel,
    reject,
)
from neorisk_simkit.engine.errors import AbiViolation, CapExceeded, EngineError

__all__ = [
    "COMMIT",
    "PRIO_CONTINUE",
    "PRIO_EXPIRY",
    "PRIO_MESSAGE",
    "PRIO_TIMER",
    "RETRY",
    "START",
    "AbiViolation",
    "ActionRef",
    "ActionSpec",
    "CapExceeded",
    "EngineError",
    "KernelSpec",
    "Local",
    "Res",
    "action",
    "kernel",
    "reject",
]
