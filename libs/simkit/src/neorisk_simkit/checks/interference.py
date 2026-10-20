"""The overlay regression rule and the interference report (§08).

Base rows are rows of base-namespace partitions that reference no overlay id. Compared with
the same run without overlays, ignoring ordering columns (`event_id`, `seq`, `cause_id`):

- Overlay shares nothing with the base (it never reached a base partition): every base row
  is identical.
- It shares state (it reached a base shard or owner at time T): base rows before T are
  identical, the pack's exogenous events (arrivals, attributes) are identical in full, laws
  hold (the ordinary checks), and the interference report shows how base outcomes changed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl

from neorisk_simkit.checks import Data, Result, _cite
from neorisk_simkit.spec.plan import NS_SPAN

ORDERING = ("event_id", "seq", "cause_id")


def _base(df: pl.DataFrame, refs: list[str]) -> pl.DataFrame:
    cond = pl.col("partition_id") < NS_SPAN
    for c in refs:
        cond = cond & (pl.col(c).is_null() | (pl.col(c) < NS_SPAN))
    return df.filter(cond)


def _refs(d: Data, table: str) -> list[str]:
    t = next(t for t in d.schema["tables"] if t["name"] == table)
    return [c["name"] for c in t["columns"] if c["type"] == "ref"]


def _diff(a: pl.DataFrame, b: pl.DataFrame, cols: list[str]) -> tuple[pl.DataFrame, int, int]:
    """Rows of `b` missing from `a` (as a multiset), and the counts each way."""
    ha = a.select(cols).hash_rows(seed=0).alias("h").value_counts(name="na")
    hb_series = b.select(cols).hash_rows(seed=0).alias("h")
    hb = hb_series.value_counts(name="nb")
    j = ha.join(hb, on="h", how="full", coalesce=True).with_columns(
        pl.col("na", "nb").fill_null(0).cast(pl.Int64))
    only_a = int((j["na"] - j["nb"]).clip(lower_bound=0).sum())
    only_b = int((j["nb"] - j["na"]).clip(lower_bound=0).sum())
    extra = j.filter(pl.col("nb") > pl.col("na"))["h"].implode()
    return b.filter(hb_series.is_in(extra)), only_a, only_b


def compare(base: Data, over: Data, contacts: dict[str, float], exogenous: set[str] = ()
            ) -> list[Result]:
    """`contacts`: base kind -> first time (seconds) an overlay partition reached it."""
    t0 = min(contacts.values()) if contacts else None
    cut = None if t0 is None else over.start + timedelta(seconds=t0)
    bad, checked, report = [], 0, {}
    for name in sorted(base.events):
        b = base.events[name]
        o = _base(over.events[name], _refs(over, name))
        cols = [c for c in b.columns if c not in ORDERING]
        bb, oo = b, o
        if cut is not None and name not in exogenous:
            bb = b.filter(pl.col("event_time") < cut)
            oo = o.filter(pl.col("event_time") < cut)
        rows, only_b, only_o = _diff(bb, oo, cols)
        checked += bb.height
        if only_b or only_o:
            bad.append(rows.select("partition_id", "seq", "action_id").with_columns(
                detail=pl.lit(f"{name}: {only_b} base rows missing, {only_o} changed or new")))
        _, nb, no = _diff(b, o, cols)
        report[name] = {"baseline": b.height, "with_overlay": o.height,
                        "only_baseline": nb, "only_with_overlay": no}
    for name, b in base.entities.items():
        key = next(t["key"] for t in base.schema["tables"] if t["name"] == name)
        o = over.entities[name].filter(pl.col(key) < NS_SPAN)
        if cut is not None:
            b, o = (x.filter(pl.col("created_at") < cut) for x in (b, o))
        _, only_b, only_o = _diff(b, o, b.columns)
        checked += b.height
        if only_b or only_o:
            msg = f"entities/{name}: {only_b} base rows missing, {only_o} changed"
            bad.append(pl.DataFrame({"detail": [msg]}))
    shared = sorted(contacts)
    rule = "identical base rows" if not shared else (
        f"identical base rows before first contact at t={t0:.0f}s; exogenous events in full")
    if bad:
        frame = pl.concat(bad, how="diagonal")
        r = Result("overlay.regression", "cross", True, "fail", checked, frame.height,
                   _cite(over, frame), detail=rule)
    else:
        r = Result("overlay.regression", "cross", True, "pass", checked, detail=rule)
    changed = {k: v for k, v in report.items() if v["only_baseline"] or v["only_with_overlay"]}
    interference = Result(
        "overlay.interference", "interference", False, "pass", len(report),
        detail=("no shared state" if not shared else
                f"shares {', '.join(shared)}; {len(changed)} event types changed for base actors"),
        metric={"shared": shared, "first_contact_s": t0, "by_event": report})
    return [r, interference]


def regression(project: Any, data: Any, baseline: str | None = None) -> list[Result]:
    """For `datagen check`: compare a dataset with overlays against its baseline."""
    from neorisk_simkit.io import read
    m = data.manifest
    base = read(baseline) if baseline else project.rerun(m, overlays=False)
    contacts: dict[str, float] = {}
    for c in m["stats"].get("contacts", []):
        contacts[c["kind"]] = min(contacts.get(c["kind"], c["t"]), c["t"])
    exo = project.plan({}).pack.exogenous
    return compare(Data.of(base), Data.of(data), contacts, exo)


def compare_outputs(base: Any, over: Any) -> list[Result]:
    """In-memory form: two `engine.Output`s of the same settings, without and with overlays."""
    contacts: dict[str, float] = {}
    for (_, kind), t in over.stats.contacts.items():
        contacts[kind] = min(contacts.get(kind, t), t)
    return compare(Data.of(base), Data.of(over), contacts, base.plan.pack.exogenous)
