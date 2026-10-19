"""`expectations.yaml`: required laws and statistical expectations of a pack (spec §11, D84).

```yaml
defaults: {min_sample: 2000, confidence: 0.95, sample_rate: 1.0}
laws: [{id: chk.x, required: true}]
expectations:
  - id: exp.y
    metric: stat.funnel(start="a", step="b", unit="a_id", within="30d")
    target: {between: [0.06, 0.10]}
    source: "brief: Rates we know, row 1"
    required: true
overlays:                       # applied only when the overlay is enabled
  <overlay>: [<expectation>, ...]
```

A `metric:` is one call `stat.<name>(...)` whose arguments are Python literals, parsed with
`ast` (never evaluated). Targets: `between: [lo, hi]` (inclusive), `lt`, `gt`, `around` with a
relative `tolerance`, `reported: true` (interference), or a per-key map of these for
`quantiles` (`p50`, `p90`, ...) and `distribution` (`median_days`, `p99_days`, ...).
`${<overlay>.<param>}` and `${<config path>}` inside targets are substituted.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from neorisk_simkit.spec.project import ProjectError, parse_duration


class ExpectationError(ValueError):
    """An `expectations.yaml` that does not follow the grammar."""


@dataclass(frozen=True)
class LawRef:
    id: str
    required: bool


@dataclass(frozen=True)
class Expectation:
    id: str
    metric: str                      # the metric name (`funnel`, `share`, ...)
    kwargs: dict
    args: tuple
    target: dict
    source: str | None
    required: bool
    overlay: str | None

    @property
    def text(self) -> str:
        """The metric call as written (normalized)."""
        parts = [repr(a) for a in self.args] + [f"{k}={v!r}" for k, v in self.kwargs.items()]
        return f"stat.{self.metric}({', '.join(parts)})"


@dataclass(frozen=True)
class Expectations:
    defaults: dict
    laws: tuple[LawRef, ...]
    items: tuple[Expectation, ...]


# The metric signatures (D84); `checks.stats` implements them with the same parameters.
def _funnel(start, step, unit, within=None, where=None): ...
def _share(event, of, where=None): ...
def _quantiles(event_or_column, per=None, where=None, cohort=None, role=None): ...
def _top_share(event, by, top): ...
def _distribution(between, unit): ...
def _cohort_size(cohort): ...
def _interference(base, cause): ...


SIGNATURES = {name[1:]: inspect.signature(f) for name, f in (
    ("_funnel", _funnel), ("_share", _share), ("_quantiles", _quantiles),
    ("_top_share", _top_share), ("_distribution", _distribution),
    ("_cohort_size", _cohort_size), ("_interference", _interference))}

DEFAULTS = {"min_sample": 1, "confidence": 0.95, "sample_rate": 1.0}
_TOP_KEYS = {"pack", "schema_version", "defaults", "laws", "expectations", "overlays"}
_ITEM_KEYS = {"id", "metric", "target", "source", "required"}
_SCALAR_TARGET = {"between", "lt", "gt", "around", "tolerance"}
_QUANTILE_KEY = re.compile(r"p(\d{1,2})")
_DISTRIBUTION_KEY = re.compile(r"median_days|p(\d{1,2})_days")
_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def parse_metric(id: str, text: Any) -> tuple[str, tuple, dict]:
    """`(name, args, kwargs)` of one `stat.<name>(...)` call with literal arguments."""
    err = ExpectationError(f"{id}: metric must be one stat.<name>(...) call with literal "
                           f"arguments")
    if not isinstance(text, str):
        raise err
    try:
        node = ast.parse(text.strip(), mode="eval").body
    except SyntaxError:
        raise err from None
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "stat"):
        raise err
    if any(k.arg is None for k in node.keywords):
        raise err
    try:
        args = tuple(ast.literal_eval(a) for a in node.args)
        kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        raise err from None
    name = node.func.attr
    if name not in SIGNATURES:
        raise ExpectationError(f"{id}: unknown metric stat.{name} (known: "
                               f"{', '.join(SIGNATURES)})")
    try:
        bound = SIGNATURES[name].bind(*args, **kwargs).arguments
    except TypeError as e:
        raise ExpectationError(f"{id}: stat.{name}: {e}") from None
    _check_args(f"{id}: stat.{name}", name, bound)
    return name, args, kwargs


def _scalar(v: Any) -> bool:
    return isinstance(v, str | int | float | bool)


def _check_args(where: str, name: str, a: Mapping[str, Any]) -> None:
    """The literal arguments' types (M-1): names are strings, `of` a string or a list of
    strings, `where` a map of column -> scalar, `top` a share in [0, 1], `within` a duration
    string (or microseconds), `between` two event names."""
    def bad(arg: str, what: str) -> ExpectationError:
        return ExpectationError(f"{where}: {arg} must be {what} (got {a[arg]!r})")

    for arg in ("start", "step", "unit", "event", "event_or_column", "per", "by", "cohort",
                "role", "base", "cause"):
        if arg in a and a[arg] is not None and not (isinstance(a[arg], str) and a[arg]):
            raise bad(arg, "a non-empty string")
    if "of" in a and not (isinstance(a["of"], str) or (
            isinstance(a["of"], list | tuple) and a["of"]
            and all(isinstance(x, str) for x in a["of"]))):
        raise bad("of", "an event name or a list of event names")
    if a.get("where") is not None and not (
            isinstance(a["where"], dict) and a["where"]
            and all(isinstance(k, str) and _scalar(v) for k, v in a["where"].items())):
        raise bad("where", "a map of column -> string, number or bool")
    if "top" in a and not (_number(a["top"]) and 0 <= a["top"] <= 1):
        raise bad("top", "a share in [0, 1]")
    w = a.get("within")
    if w is not None and not (isinstance(w, int) and not isinstance(w, bool) and w > 0):
        try:
            parse_duration(w)
        except ProjectError:
            raise bad("within", "a duration such as \"30d\"") from None
    if "between" in a and not (isinstance(a["between"], list | tuple) and len(a["between"]) == 2
                               and all(isinstance(x, str) for x in a["between"])):
        raise bad("between", "two event names")
    if name == "quantiles" and a.get("per") is not None and "." in a["event_or_column"]:
        raise ExpectationError(f"{where}: per= counts rows; give an event, not a column")


def _check_scalar_target(id: str, t: Any) -> None:
    """A comparison target (every metric but `interference`)."""
    if not isinstance(t, Mapping) or not t or set(t) - _SCALAR_TARGET:
        raise ExpectationError(f"{id}: a target is a map of {sorted(_SCALAR_TARGET)}")
    if "between" in t and not (isinstance(t["between"], list) and len(t["between"]) == 2):
        raise ExpectationError(f"{id}: between takes [lo, hi]")
    if ("around" in t) != ("tolerance" in t):
        raise ExpectationError(f"{id}: around and tolerance go together")


def _check_target(id: str, metric: str, target: Any) -> None:
    if not isinstance(target, Mapping) or not target:
        raise ExpectationError(f"{id}: target must be a non-empty map")
    if metric == "interference":                    # judged only on `reported` (D79)
        if set(target) != {"reported"} or (target["reported"] is not True
                                           and not isinstance(target["reported"], str)):
            raise ExpectationError(f"{id}: the interference target is {{reported: true}}")
        return
    keyed = {"quantiles": _QUANTILE_KEY, "distribution": _DISTRIBUTION_KEY}.get(metric)
    if keyed is None:
        _check_scalar_target(id, target)
        return
    for k, sub in target.items():
        if not isinstance(k, str) or keyed.fullmatch(k) is None:
            raise ExpectationError(f"{id}: unknown {metric} key {k!r}")
        _check_scalar_target(f"{id}.{k}", sub)


def _number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _check_numbers(x: Expectation) -> None:
    """After substitution: every bound is a number and `reported` is true."""
    subs = (x.target.items() if x.metric in ("quantiles", "distribution")
            else [(None, x.target)])
    for k, t in subs:
        where = x.id if k is None else f"{x.id}.{k}"
        bounds = [*t.get("between", []), *(t[n] for n in ("lt", "gt", "around", "tolerance")
                                            if n in t)]
        if not all(_number(b) for b in bounds):
            raise ExpectationError(f"{where}: target bounds must be numbers (got {t!r})")
        if "reported" in t and t["reported"] is not True:
            raise ExpectationError(f"{where}: reported takes true")


def _lookup(id: str, path: str, overlays: Mapping[str, Mapping], cfg: Any) -> Any:
    head, _, rest = path.partition(".")
    if head in overlays:
        if rest not in overlays[head]:
            raise ExpectationError(f"{id}: overlay {head} has no parameter {rest!r}")
        return overlays[head][rest]
    v = cfg
    for part in path.split("."):
        if isinstance(v, Mapping) and part in v:
            v = v[part]
        elif v is not None and not isinstance(v, Mapping) and hasattr(v, part):
            v = getattr(v, part)
        else:
            raise ExpectationError(f"{id}: unknown placeholder ${{{path}}}")
    return v


def _substitute(id: str, v: Any, overlays: Mapping[str, Mapping], cfg: Any) -> Any:
    if isinstance(v, Mapping):
        return {k: _substitute(id, x, overlays, cfg) for k, x in v.items()}
    if isinstance(v, list):
        return [_substitute(id, x, overlays, cfg) for x in v]
    if isinstance(v, str):
        whole = _PLACEHOLDER.fullmatch(v.strip())
        if whole:                                      # keep the parameter's type
            return _lookup(id, whole.group(1).strip(), overlays, cfg)
        return _PLACEHOLDER.sub(lambda m: str(_lookup(id, m.group(1).strip(), overlays, cfg)),
                                v)
    return v


def _item(raw: Any, overlay: str | None) -> Expectation:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise ExpectationError(f"every expectation needs an id (got {raw!r})")
    id = raw["id"]
    extra = set(raw) - _ITEM_KEYS
    if extra:
        raise ExpectationError(f"{id}: unknown keys {sorted(extra)}")
    for k in ("metric", "target"):
        if k not in raw:
            raise ExpectationError(f"{id}: {k} is required")
    name, args, kwargs = parse_metric(id, raw["metric"])
    _check_target(id, name, raw["target"])
    source = raw.get("source")
    if source is not None and not isinstance(source, str):
        raise ExpectationError(f"{id}: source must be a string")
    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise ExpectationError(f"{id}: required must be true or false")
    return Expectation(id=id, metric=name, kwargs=kwargs, args=args, target=dict(raw["target"]),
                       source=source.strip() or None if source else None, required=required,
                       overlay=overlay)


def load(path: Path, *, overlays: dict[str, dict], cfg: Any) -> Expectations:
    """Parse `expectations.yaml`. `overlays` maps every enabled overlay to its parameters (the
    sections of other overlays are checked but left out); `cfg` is the pack config the
    `${<config path>}` placeholders read."""
    try:
        doc = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as e:
        raise ExpectationError(f"{path}: {e}") from None
    doc = {} if doc is None else doc
    if not isinstance(doc, Mapping):
        raise ExpectationError(f"{path}: the top level must be a map")
    extra = set(doc) - _TOP_KEYS
    if extra:
        raise ExpectationError(f"{path}: unknown keys {sorted(extra)}")
    defaults = dict(DEFAULTS)
    given = doc.get("defaults") or {}
    if not isinstance(given, Mapping) or set(given) - set(DEFAULTS):
        raise ExpectationError(f"defaults: keys are {sorted(DEFAULTS)}")
    defaults.update(given)
    if not (isinstance(defaults["min_sample"], int) and defaults["min_sample"] >= 0):
        raise ExpectationError("defaults: min_sample must be an int >= 0")
    if not 0 < float(defaults["confidence"]) < 1:
        raise ExpectationError("defaults: confidence must be in (0, 1)")
    if not 0 < float(defaults["sample_rate"]) <= 1:
        raise ExpectationError("defaults: sample_rate must be in (0, 1]")

    laws = []
    for raw in doc.get("laws") or []:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str) \
                or set(raw) - {"id", "required"} \
                or not isinstance(raw.get("required", False), bool):
            raise ExpectationError(f"a law is {{id: <check id>, required: bool}} (got {raw!r})")
        laws.append(LawRef(raw["id"], raw.get("required", False)))

    items = [_item(raw, None) for raw in doc.get("expectations") or []]
    sections = doc.get("overlays") or {}
    if not isinstance(sections, Mapping):
        raise ExpectationError("overlays: a map of overlay name -> expectations")
    every = list(items)
    for name, rows in sections.items():
        parsed = [_item(raw, name) for raw in rows or []]
        every.extend(parsed)
        if name in overlays:
            items.extend(parsed)
    ids = [x.id for x in laws] + [x.id for x in every]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ExpectationError(f"duplicate ids {dup}")
    items = [Expectation(**{**x.__dict__, "target": _substitute(x.id, x.target, overlays, cfg)})
             for x in items]
    for x in items:
        _check_numbers(x)
    return Expectations(defaults=defaults, laws=tuple(laws), items=tuple(items))
