"""report.html: one compact, self-contained page per checked run.

Sections: summary, checks, expectations, interference, counts, transitions, linkages and
concentration, rejections, cohorts and labels. Everything is computed from the dataset and the
check results; nothing is fetched.
"""

from __future__ import annotations

import html
import json
from typing import Any

import polars as pl

from neorisk_simkit.checks import Data, Result

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mute:#6b6b70;--line:#e3e3e6;--ok:#1a7f37;--bad:#c62828;
--warn:#a15c00;--chip:#f3f3f5}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececf0;--mute:#9a9aa2;
--line:#2c2c31;--ok:#57c37a;--bad:#ff6b6b;--warn:#e0a040;--chip:#202024}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0}h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid
var(--line);padding-bottom:4px}
table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow-x:auto}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
.pass{color:var(--ok)}.fail,.error{color:var(--bad)}.inconclusive{color:var(--warn)}
.chip{display:inline-block;background:var(--chip);border-radius:6px;padding:1px 6px;
margin:2px 4px 2px 0}.mute{color:var(--mute)}code{font-size:12px}
"""


def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _num(x: Any) -> str:
    if isinstance(x, float):
        return f"{x:,.4g}"
    if isinstance(x, int) and not isinstance(x, bool):
        return f"{x:,}"
    return _e(x)


def _table(head: list[str], rows: list[list[Any]], num: set[int] = frozenset()) -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(
        f'<td class="n">{_num(c)}</td>' if i in num else f"<td>{c}</td>"
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def _status(r: Result) -> str:
    return f'<span class="{r.status}">{r.status}</span>'


def _checks(results: list[Result]) -> str:
    rows = []
    for r in results:
        if r.group in ("stat", "interference"):
            continue
        cited = "".join(f'<div class="mute"><code>{_e(json.dumps(c, default=str))}</code></div>'
                        for c in r.cited[:5])
        rows.append([_e(r.name), _e(r.group), "required" if r.required else "",
                     _status(r), r.checked, r.failures, _e(r.detail) + cited])
    return _table(["check", "group", "", "status", "checked", "failures", "detail"], rows,
                  {4, 5})


def _ci(ci: Any) -> str:
    if not ci:
        return ""
    if isinstance(ci, dict):
        return "; ".join(f"{k}: {_num(v[0])}–{_num(v[1])}" for k, v in ci.items() if v)
    return f"{_num(ci[0])}–{_num(ci[1])}"


def _expectations(results: list[Result]) -> str:
    rows = []
    for r in results:
        if r.group != "stat":
            continue
        m = r.metric or {}
        v = m.get("value")
        val = ", ".join(f"{k}={_num(x)}" for k, x in v.items()) if isinstance(v, dict) \
            else _num(v)
        rows.append([_e(r.name), f"<code>{_e(r.detail)}</code>", val, _ci(m.get("ci95")),
                     _e(json.dumps(m.get("target"))), _status(r), _e(r.doc)])
    if not rows:
        return '<p class="mute">No expectations.yaml.</p>'
    return _table(["id", "metric", "value", "95% across seeds", "target", "status", "source"],
                  rows)


def _interference(results: list[Result]) -> str:
    r = next((x for x in results if x.name == "overlay.interference"), None)
    reg = next((x for x in results if x.name == "overlay.regression"), None)
    if r is None:
        return '<p class="mute">No overlay in this run.</p>'
    head = f"<p>{_status(reg)} regression rule: {_e(reg.detail)}. {_e(r.detail)}.</p>"
    rows = [[_e(k), v["baseline"], v["with_overlay"], v["only_baseline"], v["only_with_overlay"]]
            for k, v in r.metric["by_event"].items()
            if v["only_baseline"] or v["only_with_overlay"]]
    return head + (_table(["base rows of", "baseline", "with overlay", "only in baseline",
                           "only with overlay"], rows, {1, 2, 3, 4}) if rows else "")


def _transitions(d: Data, top: int = 12) -> str:
    ev = d.all_events(["seq", "event_type", "partition_id"])
    if not ev.height:
        return ""
    kinds = d.cases.select("partition_id", "kind")
    t = (ev.with_columns(prev=pl.col("event_type").shift(1).over("partition_id"))
         .join(kinds, on="partition_id", how="left")
         .group_by("kind", "prev", "event_type").len().sort("len", descending=True))
    out = []
    for kind in t["kind"].unique(maintain_order=True):
        sub = t.filter(pl.col("kind") == kind).head(top)
        rows = [[_e(r["prev"] or "(start)"), _e(r["event_type"]), r["len"]]
                for r in sub.iter_rows(named=True)]
        out.append(f"<h3>{_e(kind)}</h3>" + _table(["from", "to", "rows"], rows, {2}))
    return "".join(out)


def _linkages(d: Data) -> str:
    rows = []
    for t in d.schema["tables"]:
        if t["group"] != "event" or t["name"] not in d.events:
            continue
        df = d.events[t["name"]]
        if not df.height:
            continue
        for c in t["columns"]:
            if c["type"] != "ref" or c["name"] in ("partition_id",):
                continue
            s = df[c["name"]].drop_nulls()
            vc = s.value_counts(sort=True)["count"] if s.len() else pl.Series([], dtype=pl.UInt32)
            k = max(1, len(vc) // 100)
            top = float(vc.head(k).sum() / vc.sum()) if len(vc) else 0.0
            rows.append([_e(f"{t['name']}.{c['name']}"), _e(c["ref"]), df.height,
                         1 - s.len() / df.height, len(vc), top])
    return _table(["column", "refers to", "rows", "null share", "distinct", "top 1% share"],
                  rows, {2, 3, 4, 5})


def _cohorts(d: Data) -> str:
    c = (d.cases.group_by("kind", "cohort").agg(pl.len().alias("cases"),
                                               pl.col("censored").mean().alias("censored"))
         .sort("kind", "cohort", nulls_last=False))
    rows = [[_e(r["kind"]), _e(r["cohort"] or "base"), r["cases"], r["censored"]]
            for r in c.iter_rows(named=True)]
    out = _table(["kind", "cohort", "cases", "censored share"], rows, {2, 3})
    if d.labels.height:
        lab = (d.labels.with_columns(delay=(pl.col("label_available_at") - pl.col("labeled_at"))
                                     .dt.total_seconds() / 86_400)
               .group_by("role", "outcome").agg(pl.len().alias("n"),
                                                pl.col("delay").median().alias("delay"))
               .sort("role", "outcome", nulls_last=True))
        out += _table(["label role", "outcome", "labels", "median days until available"],
                      [[_e(r["role"]), _e(r["outcome"]), r["n"], r["delay"]]
                       for r in lab.iter_rows(named=True)], {2, 3})
    return out


def render(run: Any, results: list[Result]) -> str:
    d = Data.of(run)
    m = getattr(run, "manifest", {}) or {}
    st = m.get("stats", {})
    bad = [r for r in results if r.required and r.status != "pass"]
    verdict = (f'<span class="fail">{len(bad)} required checks did not pass</span>' if bad
               else '<span class="pass">all required checks pass</span>')
    chips = "".join(f'<span class="chip">{_e(k)}: {_e(v)}</span>' for k, v in (
        ("pack", m.get("pack")), ("overlays", ", ".join(m.get("overlays", {})) or "none"),
        ("seed", m.get("seed")), ("revision", m.get("provenance", {}).get("pack_revision")),
        ("span", f"{d.start:%Y-%m-%d} → {d.end:%Y-%m-%d}")))
    counts = [[_e(k), v] for k, v in sorted(
        {**{f"events/{k}": df.height for k, df in d.events.items()},
         **{f"entities/{k}": df.height for k, df in d.entities.items()},
         "labels": d.labels.height}.items())]
    rej = [[_e(r["kind"]), _e(r["action"]), _e(r["reason"]), r["n"]]
           for r in st.get("rejections", [])]
    sections = [
        ("Checks", _checks(results)),
        ("Expectations", _expectations(results)),
        ("Interference", _interference(results)),
        ("Counts", _table(["table", "rows"], counts, {1})
         + f'<p class="mute">late messages {st.get("late_messages", 0)}, late replies '
           f'{st.get("late_replies", 0)}, censored cases {st.get("censored_cases", 0)}</p>'),
        ("Transitions (per partition, by kind)", _transitions(d)),
        ("Linkages and concentration", _linkages(d)),
        ("Rejections", _table(["kind", "action", "reason", "count"], rej, {3}) if rej
         else '<p class="mute">None.</p>'),
        ("Cohorts and labels", _cohorts(d)),
    ]
    body = "".join(f"<h2>{_e(t)}</h2>{s}" for t, s in sections)
    title = f"{m.get('pack', 'run')} check report"
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f'<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>"
            f"<h1>{_e(title)}</h1><p>{chips}</p><p>{verdict}</p>{body}</main></body></html>\n")
