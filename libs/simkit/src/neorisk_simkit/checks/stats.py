"""`expectations.yaml`: statistical expectations, measured exactly over the full output.

```yaml
pack: ecommerce
defaults: {min_sample: 200}          # units; fewer makes a metric inconclusive
expectations:
  - id: exp.checkout_failure_rate
    metric: stat.share("checkout_failed", of=["checkout_failed", "order_placed"])
    target: {between: [0.0, 0.05]}
    source: "brief: Rates we know, row 3"
    required: true
overlays:                            # applied only when the overlay is part of the run
  bounty_hunters: [<expectation>, ...]
```

A `metric:` is one call `stat.<name>(...)` with literal arguments, parsed with `ast` and never
evaluated. Targets: `between: [lo, hi]` (inclusive), `lt`, `gt`, `around` with a relative
`tolerance`, `reported: true` (shown, never failing), or for `quantiles` a map of these per
key (`p50`, `p90`). With held-out seeds, each value also gets a 95% interval across seeds.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from neorisk_simkit.checks import Data, Result
from neorisk_simkit.spec.dist import parse_duration


class ExpectationError(ValueError):
    pass


def _where(df: pl.DataFrame, where: dict | None) -> pl.DataFrame:
    for k, v in (where or {}).items():
        df = df.filter(pl.col(k).cast(pl.String) == str(v)) if not isinstance(v, list) else \
            df.filter(pl.col(k).cast(pl.String).is_in([str(x) for x in v]))
    return df


# --- metrics: each returns (value, n_units) ---------------------------------------------

def funnel(d: Data, start: str, step: str, unit: str, within: str | None = None,
           where: dict | None = None) -> tuple[float, int]:
    """Share of units with a `start` event that later have a `step` event (within a span)."""
    a = _where(d.ev(start), where).group_by(unit).agg(pl.col("event_time").min().alias("t0"))
    b = d.ev(step).select(unit, pl.col("event_time").alias("t1"))
    j = a.join(b, on=unit, how="left").filter(pl.col("t1") >= pl.col("t0"))
    if within:
        j = j.filter(pl.col("t1") - pl.col("t0") <= pl.duration(seconds=parse_duration(within)))
    n = a.height
    return (j[unit].n_unique() / n if n else float("nan")), n


def share(d: Data, event: str, of: list[str], where: dict | None = None) -> tuple[float, int]:
    """Rows of `event` (filtered) over rows of the `of` events."""
    num = _where(d.ev(event), where).height
    den = sum(d.ev(e).height for e in of)
    return (num / den if den else float("nan")), den


def quantiles(d: Data, event: str, per: str, where: dict | None = None,
              qs: tuple[float, ...] = (0.5, 0.9, 0.99)) -> tuple[dict, int]:
    """Quantiles of the number of `event` rows per `per` value (units with at least one)."""
    c = _where(d.ev(event), where).group_by(per).len()["len"]
    return {f"p{round(q * 100)}": float(c.quantile(q, "nearest")) if c.len() else float("nan")
            for q in qs}, c.len()


def top_share(d: Data, event: str, by: str, top: float) -> tuple[float, int]:
    """Share of `event` rows held by the top `top` fraction of `by` values."""
    c = d.ev(event).group_by(by).len().sort("len", descending=True)["len"]
    k = max(1, math.ceil(top * c.len()))
    return (float(c.head(k).sum() / c.sum()) if c.len() else float("nan")), c.len()


def rate(d: Data, event: str, where: dict | None = None) -> tuple[float, int]:
    """Rows of `event` per simulated day."""
    n = _where(d.ev(event), where).height
    return n / ((d.end - d.start).total_seconds() / 86_400.0), n


def mean(d: Data, event: str, column: str, where: dict | None = None) -> tuple[float, int]:
    df = _where(d.ev(event), where)
    return (float(df[column].mean()) if df.height else float("nan")), df.height


def count(d: Data, event: str, where: dict | None = None) -> tuple[float, int]:
    n = _where(d.ev(event), where).height
    return float(n), n


def cohort_size(d: Data, role: str) -> tuple[float, int]:
    n = d.labels.filter(pl.col("role") == role).height
    return float(n), n


METRICS = {f.__name__: f for f in (funnel, share, quantiles, top_share, rate, mean, count,
                                   cohort_size)}


# --- parsing and targets ----------------------------------------------------------------

def parse_metric(text: str) -> tuple[str, list, dict]:
    try:
        call = ast.parse(text.strip(), mode="eval").body
    except SyntaxError as exc:
        raise ExpectationError(f"metric {text!r}: {exc}") from None
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "stat"):
        raise ExpectationError(f"metric {text!r}: write stat.<name>(...)")
    name = call.func.attr
    if name not in METRICS:
        raise ExpectationError(f"metric {text!r}: unknown stat.{name}; have {sorted(METRICS)}")
    try:
        args = [ast.literal_eval(a) for a in call.args]
        kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    except ValueError:
        raise ExpectationError(f"metric {text!r}: arguments must be literals") from None
    return name, args, kwargs


def meets(value: float, target: dict) -> bool | None:
    """True/False against a target; None for `reported` (never fails)."""
    if target.get("reported"):
        return None
    if math.isnan(value):
        return False
    if "between" in target:
        lo, hi = target["between"]
        return lo <= value <= hi
    if "lt" in target:
        return value < target["lt"]
    if "gt" in target:
        return value > target["gt"]
    if "around" in target:
        c, tol = target["around"], target.get("tolerance", 0.1)
        return abs(value - c) <= abs(c) * tol
    raise ExpectationError(f"unknown target {target}")


def load(path: str | Path, overlays: list[str] = ()) -> tuple[dict, list[dict]]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    items = list(doc.get("expectations", []))
    for o in overlays:
        items += [{**e, "overlay": o} for e in (doc.get("overlays") or {}).get(o, [])]
    for e in items:
        for k in ("id", "metric", "target"):
            if k not in e:
                raise ExpectationError(f"expectation {e.get('id', '?')}: missing {k!r}")
        parse_metric(e["metric"])
    return doc.get("defaults", {}), items


def _ci(values: list[float]) -> tuple[float, float] | None:
    vals = [v for v in values if not math.isnan(v)]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
    t = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78}.get(len(vals), 2.0)
    h = t * sd / math.sqrt(len(vals))
    return m - h, m + h


def evaluate(e: dict, d: Data, others: list[Data], min_sample: int) -> Result:
    name, args, kwargs = parse_metric(e["metric"])
    fn = METRICS[name]
    required = bool(e.get("required", False))
    res = Result(e["id"], "stat", required, "pass", doc=e.get("source", ""))
    try:
        value, n = fn(d, *args, **kwargs)
        held = [fn(o, *args, **kwargs)[0] for o in others]
    except Exception as exc:  # noqa: BLE001 - a metric that cannot run is an error
        res.status, res.detail = "error", f"{type(exc).__name__}: {exc}"
        return res
    res.checked = n
    target = e["target"]
    if isinstance(value, dict):                      # quantiles: a target per key
        oks = [meets(value[k], t) for k, t in target.items()]
        cis = {k: _ci([value[k], *(h[k] for h in held)]) for k in target}
        res.metric = {"value": value, "target": target, "ci95": cis or None}
    else:
        oks = [meets(value, target)]
        res.metric = {"value": value, "target": target,
                      "ci95": _ci([value, *held]) if held else None}
    res.detail = e["metric"]
    if n < e.get("min_sample", min_sample) and not target.get("reported"):
        res.status = "inconclusive"
        res.detail += f" (n={n} < min_sample)"
    elif any(ok is False for ok in oks):
        res.status, res.failures = "fail", 1
    return res


def check_expectations(run: Any, path: str | Path, others: list[Any] = ()) -> list[Result]:
    d = Data.of(run)
    overlays = list(run.manifest["overlays"]) if hasattr(run, "manifest") else [
        o.name for o in run.plan.overlays]
    defaults, items = load(path, overlays)
    od = [Data.of(o) for o in others]
    return [evaluate(e, d, od, int(defaults.get("min_sample", 0))) for e in items]
