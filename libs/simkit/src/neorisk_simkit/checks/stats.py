"""Statistical checks: the laws and expectations of `expectations.yaml` judged on a dataset
(spec §11, D84, D85).

Cases are owners (`partition_id`). Strata are owner partition types (`partition_id // 2^56`:
base partitions and each cohort partition); an owner is sampled when
`mix64(partition_id) / 2^64 < rate`, with the stratum's rate `max(sample_rate,
min(1, min_sample / owners))`, and weighs `1 / rate` (inverse-probability weights). A cohort
owner is a whole campaign, so campaigns are sampled whole. `n_cases` (what `min_sample` counts)
is the number of the metric's units within sampled owners (D85, F-30): funnel `unit` values
and distribution units that are not censored, the rows' owners for shares and quantiles.

Exact metrics are not sampled and never inconclusive by sample size: `top_share` (`n_cases` =
its rows, inconclusive only without rows), `cohort_size` (owners) and `interference`.

Each result is `{"id", "kind": "law"|"expectation", "metric", "value", "ci", "n_cases",
"censored_share", "target", "status", "required", "source", "note"}`; `status` is `missing`
(unknown event, column, cohort or law id; no baseline for `interference`), `unanchored` (no
`source:`), `inconclusive` (`n_cases < min_sample`, no cases, a law with `checked == 0`), else
`pass` or `fail`. `ci` is `[lo, hi]`, or `{key: [lo, hi]}` for the per-key metrics
(`quantiles`, `distribution`), or None. `note` says why a result is missing.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import polars as pl

from neorisk_simkit.checks.interference import compare
from neorisk_simkit.checks.laws import _mix64
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.spec.expectations import SIGNATURES, Expectation, Expectations
from neorisk_simkit.spec.project import parse_duration

PTYPE_SHIFT = 56
DAY_US = 86_400_000_000
EXACT = ("top_share", "cohort_size", "interference")
_EPS = 1e-12


class _Missing(Exception):
    """The metric names something the dataset or the plan does not have."""


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("date=*/step-*.parquet"), key=lambda p: (p.name, p.parent.name))


class _Data:
    """The dataset of one run, read lazily (events through `read_events` when the dataset
    has a schema; folders otherwise)."""

    def __init__(self, run_dir: Path, plan: Any):
        self.dir, self.plan = Path(run_dir), plan
        self._events: dict[str, pl.DataFrame] = {}
        try:
            doc = load_schema(self.dir)
            self.names = [t["name"] for t in doc["tables"] if t["kind"] == "event"]
        except FileNotFoundError:
            ev = self.dir / "events"
            self.names = sorted(p.name for p in ev.iterdir() if p.is_dir()) if ev.is_dir() \
                else []
        m = self.dir / "manifest.json"
        self.manifest = json.loads(m.read_text()) if m.is_file() else None

    def events(self, name: str) -> pl.DataFrame:
        if name not in self.names:
            raise _Missing(f"unknown event {name!r}")
        if name not in self._events:
            if (self.dir / "schema" / "schema.json").is_file():
                df = read_events(self.dir, [name])[name]
            else:
                files = _files(self.dir / "events" / name)
                if not files:
                    raise _Missing(f"no rows of {name!r} and no schema")
                df = pl.concat([pl.read_parquet(f) for f in files])
            self._events[name] = df.with_columns(pl.col("event_time").dt.epoch("us")
                                                 .alias("_t"))
        return self._events[name]

    def column(self, col: str) -> pl.Series:
        """One column of every event table (cached tables reused, others read narrowly)."""
        parts = []
        for n in self.names:
            if n in self._events:
                parts.append(self._events[n][col])
            else:
                parts.extend(pl.read_parquet(f, columns=[col])[col]
                             for f in _files(self.dir / "events" / n))
        return pl.concat(parts) if parts else pl.Series(col, [], pl.Int64)

    def end_us(self) -> int:
        """The run's end: manifest `end_us`, else the last event time (hand-made datasets)."""
        if self.manifest is not None and self.manifest.get("end_us") is not None:
            return int(self.manifest["end_us"])
        t = self.column("event_time").dt.epoch("us").max()
        if t is None:
            raise _Missing("no events: the run's end is unknown")
        return int(t)

    def cohort(self, name: str) -> tuple[int, str | None]:
        """(`ptype_code`, label table) of a cohort of the plan."""
        cohorts = {c.name: c for c in getattr(self.plan, "cohorts", ())}
        if name not in cohorts:
            raise _Missing(f"unknown cohort {name!r}")
        part = {p.name: p for p in self.plan.partitions}[cohorts[name].partition]
        return part.ptype_code, cohorts[name].labels

    def roles(self, table: str | None) -> pl.DataFrame:
        """`(target_id, role)` of every label target, from its last label row; all label
        tables when `table` is None."""
        root = self.dir / "labels"
        names = [table] if table else (sorted(p.name for p in root.iterdir() if p.is_dir())
                                       if root.is_dir() else [])
        frames = [pl.read_parquet(f, columns=["target_id", "role"])
                  for n in names for f in _files(root / n)]
        if not frames:
            return pl.DataFrame({"target_id": [], "role": []},
                                schema={"target_id": pl.Int64, "role": pl.String})
        rows = pl.concat([f.with_columns(pl.col("role").cast(pl.String)) for f in frames])
        return rows.group_by("target_id", maintain_order=True).agg(pl.col("role").last())


# ---------------------------------------------------------------------------- helpers

def _need(df: pl.DataFrame, *cols: str) -> None:
    for c in cols:
        if c not in df.columns:
            raise _Missing(f"unknown column {c!r}")


def _where(df: pl.DataFrame, where: Mapping | None) -> pl.DataFrame:
    """Rows whose columns equal the given values (a null never matches)."""
    for c, v in (where or {}).items():
        _need(df, c)
        col = pl.col(c)
        if isinstance(v, str):
            col = col.cast(pl.String)
        df = df.filter(col.is_not_null() & (col == v))
    return df


def _ptype(col: str = "partition_id") -> pl.Expr:
    return pl.col(col) // (1 << PTYPE_SHIFT)                     # polars has no `>>` (F-07)


def _sample(owners: pl.Series, d: Mapping) -> pl.DataFrame:
    """`(partition_id, _w)` of the sampled owners among `owners` (D85)."""
    pids = np.unique(owners.drop_nulls().to_numpy().astype(np.int64))
    strata = pids // (1 << PTYPE_SHIFT)
    keep, w = np.zeros(len(pids), bool), np.zeros(len(pids), np.float64)
    for s in np.unique(strata):
        m = strata == s
        rate = max(float(d["sample_rate"]), min(1.0, d["min_sample"] / int(m.sum())))
        if rate >= 1.0:
            keep[m], w[m] = True, 1.0
        else:
            h = _mix64(pids[m].view(np.uint64))
            keep[m], w[m] = h < np.uint64(int(rate * 2.0 ** 64)), 1.0 / rate
    return pl.DataFrame({"partition_id": pids[keep], "_w": w[keep]})


def _z(d: Mapping) -> float:
    return NormalDist().inv_cdf((1 + float(d["confidence"])) / 2)


def _wilson(p: float, n: float, z: float) -> list[float] | None:
    if n <= 0:
        return None
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z / (1 + z * z / n) * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0))
    return [c - h, c + h]


def _n_eff(w: np.ndarray) -> float:
    s2 = float((w * w).sum())
    return float(w.sum()) ** 2 / s2 if s2 > 0 else 0.0


def _wquantile(v: np.ndarray, w: np.ndarray, q: float) -> Any:
    """The smallest value whose cumulative weight share reaches `q` (an order statistic)."""
    o = np.argsort(v, kind="stable")
    cw = np.cumsum(w[o]) / w.sum()
    i = min(int(np.searchsorted(cw, q - _EPS, side="left")), len(v) - 1)
    return v[o][i].item()


def _levels(target: Mapping) -> dict[str, float]:
    out = {}
    for k in target:
        if k == "median_days":
            out[k] = 0.5
        else:
            out[k] = int(re.fullmatch(r"p(\d{1,2})(?:_days)?", k).group(1)) / 100
    return out


def _quantiles(v: np.ndarray, w: np.ndarray, levels: Mapping[str, float],
               z: float) -> tuple[dict | None, dict | None]:
    """Weighted quantiles with a binomial order-statistic interval (normal approximation of
    the rank's binomial on the effective case count)."""
    if len(v) == 0:
        return None, None
    n = _n_eff(w)
    val, ci = {}, {}
    for k, q in levels.items():
        h = z * math.sqrt(q * (1 - q) / n)
        val[k] = _wquantile(v, w, q)
        ci[k] = [_wquantile(v, w, max(q - h, 0.0)), _wquantile(v, w, min(q + h, 1.0))]
    return val, ci


def _result(**kw: Any) -> dict:
    base = {"value": None, "ci": None, "n_cases": None, "censored_share": None, "note": None}
    return {**base, **kw}


# ---------------------------------------------------------------------------- metrics

def _first_starts(df: pl.DataFrame, unit: str) -> pl.DataFrame:
    """Per non-null `unit`: the first time `_t0` and the owner of its first row."""
    return (df.filter(pl.col(unit).is_not_null()).sort("_t", "partition_id")
            .group_by(unit, maintain_order=True)
            .agg(pl.col("_t").first().alias("_t0"), pl.col("partition_id").first()))


def _m_funnel(data: _Data, d: Mapping, start, step, unit, within=None, where=None) -> dict:
    s, st = data.events(start), data.events(step)
    _need(s, unit)
    _need(st, unit)
    s = _where(s, where)
    first = _first_starts(s, unit)
    cases = first.join(_sample(first["partition_id"], d), on="partition_id", how="inner")
    if within is not None:
        w_us = parse_duration(within) if isinstance(within, str) else int(within)
        cases = cases.with_columns((pl.col("_t0") > data.end_us() - w_us).alias("_cens"))
    else:
        w_us = None
        cases = cases.with_columns(pl.lit(False).alias("_cens"))
    steps = st.filter(pl.col(unit).is_not_null()).select(unit, pl.col("_t").alias("_ts"))
    hit = cases.join(steps, on=unit, how="inner").filter(pl.col("_ts") >= pl.col("_t0"))
    if w_us is not None:
        hit = hit.filter(pl.col("_ts") <= pl.col("_t0") + w_us)
    hit = hit.select(unit).unique().with_columns(pl.lit(True).alias("_conv"))
    cases = (cases.join(hit, on=unit, how="left")
             .with_columns(pl.col("_conv").fill_null(False)))
    w_all = cases["_w"].to_numpy()
    cens = cases["_cens"].to_numpy()
    kept = cases.filter(~pl.col("_cens"))
    w, conv = kept["_w"].to_numpy(), kept["_conv"].to_numpy()
    cs = float(w_all[cens].sum() / w_all.sum()) if w_all.sum() > 0 else None
    if w.sum() <= 0:
        return _result(n_cases=0, censored_share=cs)
    p = float((w * conv).sum() / w.sum())
    return _result(value=p, ci=_wilson(p, _n_eff(w), _z(d)), n_cases=kept.height,
                   censored_share=cs)


def _owner_counts(df: pl.DataFrame, name: str) -> pl.DataFrame:
    return df.group_by("partition_id").agg(pl.len().cast(pl.Float64).alias(name))


def _m_share(data: _Data, d: Mapping, event, of, where=None) -> dict:
    num = _where(data.events(event), where)
    of = [of] if isinstance(of, str) else list(of)
    den = pl.concat([data.events(o).select("partition_id") for o in of])
    owners = (_owner_counts(num, "_y").join(_owner_counts(den, "_x"), on="partition_id",
                                            how="full", coalesce=True)
              .with_columns(pl.col("_y").fill_null(0.0), pl.col("_x").fill_null(0.0)))
    owners = owners.join(_sample(owners["partition_id"], d), on="partition_id", how="inner")
    w, y, x = (owners[c].to_numpy() for c in ("_w", "_y", "_x"))
    n = owners.height
    sx = float((w * x).sum())
    if sx <= 0:
        return _result(n_cases=n, censored_share=0.0)
    r = float((w * y).sum()) / sx
    ci = None
    if n > 1:                                   # delta method on per-owner sums
        e = w * (y - r * x)
        se = math.sqrt(n / (n - 1) * float((e * e).sum())) / sx
        ci = [r - _z(d) * se, r + _z(d) * se]
    return _result(value=r, ci=ci, n_cases=n, censored_share=0.0)


def _m_quantiles(data: _Data, d: Mapping, target: Mapping, event_or_column, per=None,
                 where=None, cohort=None, role=None) -> dict:
    name, _, col = event_or_column.partition(".")
    df = _where(data.events(name), where)
    labels = None
    if cohort is not None:
        ptype, labels = data.cohort(cohort)
        df = df.filter(_ptype() == ptype)
    if role is not None:
        if cohort is not None and labels is None:
            raise _Missing(f"cohort {cohort!r} has no labels")
        _need(df, "user_id")
        r = data.roles(labels)
        ids = r.filter(pl.col("role") == role).select(pl.col("target_id").alias("user_id"))
        df = df.join(ids.with_columns(pl.col("user_id").cast(df.schema["user_id"])),
                     on="user_id", how="semi")
    if per is not None:
        _need(df, per)
        vals = (df.filter(pl.col(per).is_not_null()).sort("_t", "partition_id")
                .group_by(per, maintain_order=True)
                .agg(pl.len().alias("_v"), pl.col("partition_id").first()))
    elif col:
        _need(df, col)
        vals = df.filter(pl.col(col).is_not_null()).select(pl.col(col).alias("_v"),
                                                          "partition_id")
    else:
        raise _Missing(f"quantiles of {name!r} need a column (<event>.<column>) or per=")
    vals = vals.join(_sample(vals["partition_id"], d), on="partition_id", how="inner")
    value, ci = _quantiles(vals["_v"].to_numpy(), vals["_w"].to_numpy(),
                           _levels(target), _z(d))
    return _result(value=value, ci=ci, n_cases=vals["partition_id"].n_unique(),
                   censored_share=0.0)


def _m_distribution(data: _Data, d: Mapping, target: Mapping, between, unit) -> dict:
    a, b = between
    da, db = data.events(a), data.events(b)
    _need(da, unit)
    _need(db, unit)
    first = _first_starts(da, unit)
    cases = first.join(_sample(first["partition_id"], d), on="partition_id", how="inner")
    ends = (cases.join(db.filter(pl.col(unit).is_not_null()).select(unit, pl.col("_t")
                                                                    .alias("_t1")),
                       on=unit, how="inner")
            .filter(pl.col("_t1") >= pl.col("_t0")).group_by(unit).agg(pl.col("_t1").min()))
    cases = cases.join(ends, on=unit, how="left")
    done = cases.filter(pl.col("_t1").is_not_null())
    w_all = cases["_w"].to_numpy()
    cs = float(1 - done["_w"].sum() / w_all.sum()) if w_all.sum() > 0 else None
    gaps = ((done["_t1"] - done["_t0"]).cast(pl.Float64) / DAY_US).to_numpy()
    value, ci = _quantiles(gaps, done["_w"].to_numpy(), _levels(target),
                           _z(d))
    return _result(value=value, ci=ci, n_cases=done.height, censored_share=cs)


def _m_top_share(data: _Data, event, by, top) -> dict:
    df = data.events(event)
    _need(df, by)
    counts = df.filter(pl.col(by).is_not_null()).group_by(by).agg(pl.len().alias("_n"))
    total = int(counts["_n"].sum()) if counts.height else 0
    if total == 0:
        return _result(n_cases=0)
    k = math.ceil(top * counts.height - 1e-9)
    head = counts.sort("_n", descending=True)["_n"].head(max(k, 0))
    return _result(value=int(head.sum()) / total, n_cases=total)


def _m_cohort_size(data: _Data, cohort) -> dict:
    ptype, _ = data.cohort(cohort)
    pid = data.column("partition_id").drop_nulls()
    n = pid.filter(pid // (1 << PTYPE_SHIFT) == ptype).n_unique()
    return _result(value=n, n_cases=n)


def _m_interference(data: _Data, baseline: Path | None, base, cause) -> dict:
    data.events(base)
    if baseline is None:
        raise _Missing("interference needs a baseline run (--baseline)")
    if data.plan is None:
        raise _Missing("interference needs the run's plan")
    rep = compare(baseline, data.dir, data.plan)
    return _result(value=rep)


# ---------------------------------------------------------------------------- targets

def _meets(v: Any, t: Mapping) -> bool:
    ok = True
    if "between" in t:
        lo, hi = t["between"]
        ok &= lo <= v <= hi
    if "lt" in t:
        ok &= v < t["lt"]
    if "gt" in t:
        ok &= v > t["gt"]
    if "around" in t:
        ok &= abs(v - t["around"]) <= t["tolerance"] * abs(t["around"])
    return bool(ok)


def _judge(x: Expectation, kw: Mapping, value: Any) -> bool:
    if x.metric == "interference":
        return kw["cause"] in value.get("shared", ())
    if x.metric in ("quantiles", "distribution"):
        return all(_meets(value[k], t) for k, t in x.target.items())
    return _meets(value, x.target)


def _evaluate_one(x: Expectation, data: _Data, d: Mapping, baseline: Path | None) -> dict:
    kw = SIGNATURES[x.metric].bind(*x.args, **x.kwargs).arguments
    head = {"id": x.id, "kind": "expectation", "metric": x.text, "target": x.target,
            "required": x.required, "source": x.source}
    try:
        if x.metric == "funnel":
            r = _m_funnel(data, d, **kw)
        elif x.metric == "share":
            r = _m_share(data, d, **kw)
        elif x.metric == "quantiles":
            r = _m_quantiles(data, d, x.target, **kw)
        elif x.metric == "distribution":
            r = _m_distribution(data, d, x.target, **kw)
        elif x.metric == "top_share":
            r = _m_top_share(data, **kw)
        elif x.metric == "cohort_size":
            r = _m_cohort_size(data, **kw)
        else:
            r = _m_interference(data, baseline, **kw)
    except _Missing as e:
        return {**head, **_result(note=str(e)), "status": "missing"}
    if not x.source:
        status = "unanchored"
    elif r["value"] is None or (x.metric not in EXACT and r["n_cases"] < d["min_sample"]):
        status = "inconclusive"
    else:
        status = "pass" if _judge(x, kw, r["value"]) else "fail"
    return {**head, **r, "status": status}


def _law(ref: Any, laws: Mapping | None) -> dict:
    head = {"id": ref.id, "kind": "law", "metric": "law", "target": {"violations": 0},
            "required": ref.required, "source": "pack: p.check"}
    if laws is None or ref.id not in laws:
        return {**head, **_result(note=f"law {ref.id!r} is not in the manifest"),
                "status": "missing"}
    v = laws[ref.id]
    checked, violations = int(v.get("checked", 0)), int(v.get("violations", 0))
    status = "inconclusive" if checked == 0 else ("pass" if violations == 0 else "fail")
    return {**head, **_result(value=violations, n_cases=checked), "status": status}


def evaluate(exp: Expectations, run_dir: Path, plan: Any, *,
             baseline: Path | None) -> list[dict]:
    """One result per law and expectation of `exp`, judged on the dataset in `run_dir`
    (`plan`: the run's plan, for cohorts and `interference`; `baseline`: the dataset of the
    same run without overlays)."""
    data = _Data(run_dir, plan)
    laws = data.manifest.get("laws") if data.manifest is not None else None
    out = [_law(ref, laws) for ref in exp.laws]
    out += [_evaluate_one(x, data, exp.defaults, baseline) for x in exp.items]
    return out
