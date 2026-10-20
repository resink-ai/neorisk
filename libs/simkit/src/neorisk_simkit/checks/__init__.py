"""Checks (§11): Polars queries over a finished run, never streaming reducers.

    structural   types, required values, uniqueness, references, ordering keys, leakage
    law          per-partition laws: lifecycles, running sums, holds resolved, sequences
    cross        cross-partition laws: reservations by TTL, pool caps, request/response pairs
    stat         statistical expectations (expectations.yaml), exact over the full output

A check is `fn(d: Data) -> (n_checked, bad)`, where `bad` is a frame of offending rows with
`partition_id`, `seq` and `action_id` where they exist, and an optional `detail`. Failures
cite `(partition_id, seq, action)`. Laws are built by the factories in `checks.laws`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from neorisk_simkit.schema import schema_json
from neorisk_simkit.spec.types import COMMON, polars_type

MAX_CITED = 20


@dataclass
class Data:
    """A finished run as frames: from `engine.Output` or `io.RunData`."""
    events: dict[str, pl.DataFrame]
    entities: dict[str, pl.DataFrame]
    labels: pl.DataFrame
    cases: pl.DataFrame
    schema: dict
    cfg: dict
    start: datetime
    end: datetime

    @classmethod
    def of(cls, run: Any) -> Data:
        if isinstance(run, Data):
            return run
        from neorisk_simkit.engine.output import Output
        from neorisk_simkit.io.writer import _jsonable
        if isinstance(run, Output):
            schema, cfg = schema_json.build(run.plan), _jsonable(run.cfg) or {}
            start, days = run.run.start, run.run.days
        else:                                            # io.RunData
            schema, cfg = run.schema, run.manifest["config"] or {}
            start = datetime.fromisoformat(run.manifest["run"]["start"])
            days = run.manifest["run"]["days"]
        return cls(run.events, run.entities, run.labels, run.cases, schema, cfg, start,
                   start + timedelta(days=days))

    def ev(self, name: str) -> pl.DataFrame:
        if name in self.events:
            return self.events[name]
        cols = schema_json.table_columns(self.schema, name)
        return pl.DataFrame(schema={c: polars_type(t) for c, t in cols.items()})

    def action(self, action_id: int | None) -> str | None:
        if action_id is None:
            return None
        a = self.schema["actions"][action_id]
        return f"{a['kind']}.{a['name']}"

    def all_events(self, cols: list[str] | None = None) -> pl.DataFrame:
        keep = cols or list(COMMON)
        frames = [df.select(keep) for df in self.events.values() if df.height]
        if not frames:
            return pl.DataFrame(schema={c: polars_type(COMMON[c]) for c in keep})
        return pl.concat(frames).sort("seq")

    def value(self, v: Any) -> Any:
        """A law parameter: a literal, or the name of a config field ("cfg.monthly_cap")."""
        if isinstance(v, str) and v.startswith("cfg."):
            return self.cfg[v[4:]]
        return v


@dataclass
class Result:
    name: str
    group: str
    required: bool
    status: str                      # pass | fail | error | inconclusive
    checked: int = 0
    failures: int = 0
    cited: list[dict] = field(default_factory=list)
    doc: str = ""
    detail: str = ""
    metric: dict | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [])}


def _cite(d: Data, bad: pl.DataFrame) -> list[dict]:
    rows = []
    for r in bad.head(MAX_CITED).iter_rows(named=True):
        c = {k: r.get(k) for k in ("partition_id", "seq") if k in r}
        if "action_id" in r:
            c["action"] = d.action(r["action_id"])
        if "detail" in r:
            c["detail"] = r["detail"]
        for k, v in r.items():
            if k not in c and k not in ("action_id", "detail") and len(c) < 8:
                c[k] = v if isinstance(v, (int, float, str, bool)) or v is None else str(v)
        rows.append(c)
    return rows


def run_check(d: Data, name: str, fn, *, group: str = "law", required: bool = True,
              doc: str = "") -> Result:
    try:
        out = fn(d)
    except Exception as exc:  # noqa: BLE001 - a broken check is reported as an error
        return Result(name, group, required, "error", doc=doc,
                      detail=f"{type(exc).__name__}: {exc}")
    if isinstance(out, Result):
        return out
    n, bad = out
    if bad.height:
        return Result(name, group, required, "fail", n, bad.height, _cite(d, bad), doc)
    return Result(name, group, required, "pass", n, doc=doc)


def run_checks(run: Any, specs: list = (), *, structural: bool = True) -> list[Result]:
    """Structural checks (unless turned off), then the pack's and overlays' declared checks."""
    from neorisk_simkit.checks import structural as st
    d = Data.of(run)
    results = st.run_all(d) if structural else []
    for c in specs:
        results.append(run_check(d, c.name, c.fn, group=c.group, required=c.required,
                                 doc=c.doc))
    return results


def failed(results: list[Result]) -> list[Result]:
    """Required checks that did not pass (fail, error or inconclusive)."""
    return [r for r in results if r.required and r.status != "pass"]
