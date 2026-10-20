"""Run a plan and turn its column lists into typed Polars frames in canonical order."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from neorisk_simkit.engine.loop import DAY, Engine, RunConfig, SimError, Stats
from neorisk_simkit.spec.plan import Plan
from neorisk_simkit.spec.types import INT64_MAX, INT64_MIN, LType, polars_type

LABEL_SCHEMA = {"target_id": pl.Int64, "final_label": pl.Int32, "role": pl.String,
                "outcome": pl.String, "campaign_id": pl.Int64,
                "labeled_at": pl.Datetime("us", "UTC"),
                "label_available_at": pl.Datetime("us", "UTC")}


@dataclass
class Output:
    plan: Plan
    cfg: Any
    run: RunConfig
    events: dict[str, pl.DataFrame]
    entities: dict[str, pl.DataFrame]
    labels: pl.DataFrame
    cases: pl.DataFrame
    snapshots: dict[str, pl.DataFrame]
    stats: Stats
    timings: dict[str, float] = field(default_factory=dict)

    def all_events(self, cols: list[str] | None = None) -> pl.DataFrame:
        """Every event in canonical order, over the common columns (or `cols`)."""
        from neorisk_simkit.spec.types import COMMON
        keep = cols or list(COMMON)
        frames = [df.select(keep) for df in self.events.values() if df.height]
        if not frames:
            return pl.DataFrame(schema={c: polars_type(COMMON[c]) for c in keep})
        return pl.concat(frames, how="vertical").sort("seq")


def _times(start_us: int, secs: list[float]) -> pl.Series:
    us = (np.asarray(secs, dtype=np.float64) * 1e6).round().astype(np.int64) + start_us
    return pl.Series(us).cast(pl.Datetime("us", "UTC"))


def _column(name: str, t: LType, values: list, start_us: int, table: str) -> pl.Series:
    if t.kind == "ts":
        if any(v is None for v in values):
            s = pl.Series(name, values, dtype=pl.Float64)
            us = (s * 1e6).round().cast(pl.Int64) + start_us
            return us.cast(pl.Datetime("us", "UTC")).alias(name)
        return _times(start_us, values).alias(name)
    if t.kind in ("i64", "ref", "amount", "i32"):
        bad = [v for v in values if type(v) is int and not INT64_MIN <= v <= INT64_MAX]
        if bad:
            raise SimError(f"{table}.{name}: {bad[0]} is out of int64 range")
    try:
        return pl.Series(name, values, dtype=polars_type(t), strict=True)
    except Exception as exc:
        raise SimError(f"{table}.{name}: values do not fit {t.kind}: {exc}") from exc


def _frame(table, lists: dict[str, list], start_us: int) -> pl.DataFrame:
    cols = table.columns()
    n = len(next(iter(lists.values()))) if lists else 0
    series = []
    for c, t in cols.items():
        if c == "event_type":
            series.append(pl.Series(c, [table.name] * n, dtype=pl.String))
            continue
        s = _column(c, t, lists[c], start_us, table.name)
        if not t.nullable and s.null_count():
            raise SimError(f"{table.name}.{c}: {s.null_count()} null values in a required column")
        series.append(s)
    return pl.DataFrame(series)


def simulate(plan: Plan, cfg: Any, run: RunConfig | None = None) -> Output:
    run = run or RunConfig()
    t0 = time.perf_counter()
    e = Engine(plan, cfg, run)
    e.run_sources()
    e.loop()
    t1 = time.perf_counter()
    start_us = int(run.start.timestamp() * 1_000_000)
    warm_us = start_us + int(run.warmup_days * DAY * 1e6)
    events = {}
    for name, t in plan.events.items():
        df = _frame(t, e._ev[name][1], start_us)
        if run.warmup_days:
            df = df.filter(pl.col("event_time") >= pl.lit(warm_us).cast(pl.Datetime("us", "UTC")))
        events[name] = df
    entities = {name: _frame(t, e._ent[name], start_us) for name, t in plan.entities.items()}
    lab = e.labels
    labels = pl.DataFrame({
        "target_id": lab["target_id"], "final_label": [1] * len(lab["target_id"]),
        "role": lab["role"], "outcome": lab["outcome"], "campaign_id": lab["campaign_id"],
        "labeled_at": _times(start_us, lab["labeled_at"]),
        "label_available_at": _times(start_us, lab["label_available_at"]),
    }, schema=LABEL_SCHEMA).unique("target_id", keep="last", maintain_order=True)
    parts = list(e.parts.values())
    cases = pl.DataFrame({
        "partition_id": [p.pid for p in parts], "kind": [p.kind.name for p in parts],
        "cohort": [p.cohort for p in parts], "depth": [p.depth for p in parts],
        "created_at": _times(start_us, [p.created_at for p in parts]),
        "retired_at": pl.Series([p.retired_at for p in parts], dtype=pl.Float64),
        "steps": [p.steps for p in parts],
    }, schema_overrides={"cohort": pl.String, "partition_id": pl.Int64, "depth": pl.Int32,
                         "steps": pl.Int64})
    cases = cases.with_columns(
        censored=pl.col("retired_at").is_null(),
        retired_at=((pl.col("retired_at") * 1e6).round().cast(pl.Int64) + start_us)
        .cast(pl.Datetime("us", "UTC")))
    snaps = {k: pl.DataFrame(rows) for k, rows in (e.snapshot or {}).items()}
    t2 = time.perf_counter()
    return Output(plan, cfg, run, events, entities, labels, cases, snaps, e.stats,
                  {"loop_s": t1 - t0, "frames_s": t2 - t1})
