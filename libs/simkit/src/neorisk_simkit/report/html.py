"""`report.html` of a run: one self-contained page (inline CSS, no scripts, no network) with
the sections of spec §02/§16 in order — Counts, Linkages, Transitions, Concentration,
Rejections, Cohorts, Interference, Checks (D86).

Sources: `manifest.json` (counts, pairing, late messages), `run_stats.json` (`machines`,
`rejects`), the dataset's event, entity and label folders (concentration, cohorts), the plan
(`cohorts`), the interference report of `checks.interference.compare` and the result rows of
`checks.stats.evaluate`. Every interpolated value is HTML-escaped.

Concentration is exact and cheap: for each event type, only its first `ref` column other than
the common columns is read (never the whole table), grouped by value; the top-1% share is the
rows of the `ceil(1% · distinct values)` most frequent values over the column's non-null rows.
"""

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

from neorisk_simkit.spec.types import COMMON_COLUMNS

SECTIONS = ("Counts", "Linkages", "Transitions", "Concentration", "Rejections", "Cohorts",
            "Interference", "Checks")
TOP = 0.01                                   # the concentration share's head (top 1%)
_COMMON = frozenset(c for c, _ in COMMON_COLUMNS)
_SCROLL_ROWS = 25                            # longer tables scroll under a sticky header
_GOOD = {"pass"}
_BAD = {"fail", "missing", "inconclusive", "unanchored"}

_CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6a66;--line:#e2e1dc;--head:#f1f0ec;
--ok:#1f7a3d;--ok-bg:#e3f3e7;--bad:#a1261b;--bad-bg:#fbe5e2;--warn:#8a5a00;--warn-bg:#fdf1d8}
@media (prefers-color-scheme:dark){:root{--bg:#18181a;--fg:#e8e7e3;--muted:#9c9b96;
--line:#33332f;--head:#232322;--ok:#7fd49a;--ok-bg:#1d3324;--bad:#f2948a;--bad-bg:#3d1f1c;
--warn:#f0c46a;--warn-bg:#3a2e14}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:76rem;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.4rem;margin:0 0 4px}
h2{font-size:1.1rem;margin:32px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
h3{font-size:.95rem;margin:16px 0 6px}
p{margin:6px 0}
.muted{color:var(--muted)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:6px;margin:6px 0 12px}
.wrap.long{max-height:28rem;overflow-y:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:4px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{position:sticky;top:0;background:var(--head);font-weight:600;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:0}
code{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
.pill{display:inline-block;padding:0 8px;border-radius:9px;font-size:12px;font-weight:600}
.ok{color:var(--ok);background:var(--ok-bg)}
.bad{color:var(--bad);background:var(--bad-bg)}
.warn{color:var(--warn);background:var(--warn-bg)}
.banner{padding:8px 12px;border-radius:6px;margin:12px 0}
"""


class _Html(str):
    """A table cell that is already HTML (built from escaped parts)."""


def _e(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


# ---------------------------------------------------------------------------- formatting

def _fmt(v: Any) -> str:
    """A value as plain text (escaped by the caller)."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return "—" if math.isnan(v) else f"{v:.4g}"
    if isinstance(v, Mapping):
        return "; ".join(f"{k} {_fmt(x)}" for k, x in v.items())
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


def _pct(v: Any) -> str:
    return "—" if v is None else f"{100 * float(v):.1f}%"


def _value(v: Any) -> str:
    if isinstance(v, Mapping) and "shared" in v and "changed_owners" in v:   # interference
        shared = ", ".join(v["shared"]) or "none"
        return f"reported (shared: {shared})"
    return _fmt(v)


def _ci(ci: Any) -> str:
    if ci is None:
        return "—"
    if isinstance(ci, Mapping):
        return "; ".join(f"{k} {_fmt(x)}" for k, x in ci.items())
    return _fmt(ci)


def _bound(t: Mapping) -> str:
    parts = []
    if "between" in t:
        lo, hi = t["between"]
        parts.append(f"in [{_fmt(lo)}, {_fmt(hi)}]")
    if "lt" in t:
        parts.append(f"< {_fmt(t['lt'])}")
    if "gt" in t:
        parts.append(f"> {_fmt(t['gt'])}")
    if "around" in t:
        parts.append(f"{_fmt(t['around'])} ± {_fmt(100 * float(t['tolerance']))}%")
    if "reported" in t:
        parts.append("reported")
    if "holds" in t:
        parts.append("holds")
    if "violations" in t:
        parts.append(f"{_fmt(t['violations'])} violations")
    return ", ".join(parts) or _fmt(dict(t))


def _target(t: Any) -> str:
    if not isinstance(t, Mapping):
        return _fmt(t)
    if t and all(isinstance(x, Mapping) for x in t.values()):           # per-key targets
        return "; ".join(f"{k}: {_bound(x)}" for k, x in t.items())
    return _bound(t)


def _pill(text: str, kind: str) -> _Html:
    return _Html(f'<span class="pill {kind}">{_e(text)}</span>')


def _status(status: str, required: bool) -> _Html:
    if status in _GOOD:
        return _pill(status, "ok")
    return _pill(status, "bad" if required else "warn")


def _flag(ok: Any) -> _Html | str:
    """A yes/no outcome of the regression rule (None: not applicable)."""
    if ok is None:
        return "n/a"
    return _pill("yes", "ok") if ok else _pill("no", "bad")


def _cell(v: Any) -> str:
    return v if isinstance(v, _Html) else _e(_fmt(v))


def _table(head: Sequence[str], rows: Sequence[Sequence[Any]], numeric: Sequence[int] = (),
           empty: str = "none") -> str:
    if not rows:
        return f'<p class="muted">{_e(empty)}</p>'
    num = set(numeric)
    th = "".join(f'<th class="n">{_e(h)}</th>' if i in num else f"<th>{_e(h)}</th>"
                 for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td class="n">{_cell(v)}</td>' if i in num
                                    else f"<td>{_cell(v)}</td>" for i, v in enumerate(r))
                   + "</tr>" for r in rows)
    long = " long" if len(rows) > _SCROLL_ROWS else ""
    return (f'<div class="wrap{long}"><table><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _section(title: str, body: str) -> str:
    return f'<section id="{_e(title.lower())}"><h2>{_e(title)}</h2>{body}</section>'


# ---------------------------------------------------------------------------- sections

def _counts(m: Mapping) -> str:
    rows = []
    for key, kind in (("counts", "event"), ("posting_counts", "posting"),
                      ("label_counts", "label"), ("entity_counts", "entity"),
                      ("history_counts", "history")):
        rows += [[kind, name, n] for name, n in sorted((m.get(key) or {}).items())]
    totals = []
    for key, kind in (("counts", "event"), ("posting_counts", "posting"),
                      ("label_counts", "label"), ("entity_counts", "entity"),
                      ("history_counts", "history")):
        d = m.get(key) or {}
        totals.append(f"{_fmt(sum(d.values()))} {kind} rows in {len(d)} tables")
    return (f'<p class="muted">{_e(" · ".join(totals))}</p>'
            + _table(("kind", "table", "rows"), rows, numeric=(2,), empty="no manifest"))


def _linkages(m: Mapping) -> str:
    rows = [[b, d.get("requests", 0), d.get("responses", 0),
             d.get("requests", 0) - d.get("responses", 0)]
            for b, d in sorted((m.get("pairing") or {}).items())]
    late = m.get("late_messages")
    return (f"<p>Late messages (addressed to an absent or retired owner): "
            f"<b>{_e(_fmt(late))}</b></p>"
            + _table(("request boundary", "requests", "responses", "unanswered"), rows,
                     numeric=(1, 2, 3), empty="no request boundaries"))


def _transitions(st: Mapping) -> str:
    machines = st.get("machines") or {}
    if not machines:
        return '<p class="muted">no machines</p>'
    head = [[name, d.get("spawned"), d.get("rejects"), d.get("late"), d.get("late_grants")]
            for name, d in sorted(machines.items())]
    entries = [[name, state, n] for name, d in sorted(machines.items())
               for state, n in (d.get("entries") or {}).items()]
    return ("<h3>Per machine</h3>"
            + _table(("machine", "spawned", "rejected parts", "late", "late grants"), head,
                     numeric=(1, 2, 3, 4))
            + "<h3>State entries</h3>"
            + _table(("machine", "state", "entries"), entries, numeric=(2,)))


def _step_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("date=*/step-*.parquet"), key=lambda p: (p.name, p.parent.name))


def _concentration(run_dir: Path) -> str:
    schema = _read_json(run_dir / "schema" / "schema.json")
    rows = []
    for t in sorted((t for t in schema.get("tables", []) if t.get("kind") == "event"),
                    key=lambda t: t["name"]):
        col = next((c["name"] for c in t["columns"]
                    if c.get("ref") and c["name"] not in _COMMON), None)
        if col is None:
            rows.append([t["name"], "—", None, None, None, None])
            continue
        files = _step_files(run_dir / "events" / t["name"])
        if not files:
            rows.append([t["name"], col, 0, 0, None, None])
            continue
        counts = (pl.scan_parquet(files, hive_partitioning=False).select(col)
                  .drop_nulls().group_by(col).agg(pl.len().alias("_n")).collect())
        total = int(counts["_n"].sum()) if counts.height else 0
        if total == 0:
            rows.append([t["name"], col, 0, 0, None, None])
            continue
        k = max(1, math.ceil(TOP * counts.height - 1e-9))
        top = int(counts["_n"].sort(descending=True).head(k).sum())
        rows.append([t["name"], col, total, counts.height, k, _Html(_e(_pct(top / total)))])
    return ('<p class="muted">Exact, per event type, by its first reference column other than '
            "the common columns: the share of rows held by the top 1% of its values.</p>"
            + _table(("event", "by", "rows", "distinct", "top-1% values", "top-1% share"),
                     rows, numeric=(2, 3, 4, 5), empty="no schema"))


def _rejections(st: Mapping) -> str:
    rows = [[p, n] for p, n in sorted((st.get("rejects") or {}).items())]
    return _table(("process", "rejected commands"), rows, numeric=(1,),
                  empty="no run_stats.json")


def _entity_files(run_dir: Path, table: str) -> list[Path]:
    return sorted((run_dir / "entities" / table).glob("*.parquet"))


def _cohorts(run_dir: Path, m: Mapping, plan: Any) -> str:
    cohorts = tuple(getattr(plan, "cohorts", ()) or ())
    if not cohorts:
        return '<p class="muted">no cohorts</p>'
    parts = {p.name: p for p in plan.partitions}
    per_table: dict[str, list[str]] = {}
    for c in cohorts:
        per_table.setdefault(c.table, []).append(c.name)
    members: dict[str, int] = {}
    for table in per_table:
        files = _entity_files(run_dir, table)
        members[table] = (int(pl.scan_parquet(files).select("origin")
                              .filter(pl.col("origin") == "member").select(pl.len())
                              .collect().item()) if files else 0)
    entity_counts = m.get("entity_counts") or {}
    label_counts = m.get("label_counts") or {}
    head, roles = [], []
    for c in cohorts:
        shared = len(per_table[c.table]) > 1
        n_members = members[c.table]
        head.append([c.name, c.overlay, c.table, entity_counts.get(parts[c.partition].table, 0),
                     f"{n_members:,} (all cohorts on {c.table})" if shared else n_members,
                     c.labels or "—", label_counts.get(c.labels) if c.labels else None])
        files = _step_files(run_dir / "labels" / c.labels) if c.labels else []
        if files:
            g = (pl.scan_parquet(files, hive_partitioning=False).select("role", "outcome")
                 .with_columns(pl.col("role").cast(pl.String), pl.col("outcome")
                               .cast(pl.String))
                 .group_by("role", "outcome").agg(pl.len().alias("_n"))
                 .sort("role", "outcome").collect())
            roles += [[c.name, r, o, n] for r, o, n in g.iter_rows()]
    return (_table(("cohort", "overlay", "member table", "owners", "members", "label table",
                    "label rows"), head, numeric=(3, 4, 6))
            + "<h3>Label rows by role and outcome</h3>"
            + _table(("cohort", "role", "outcome", "rows"), roles, numeric=(3,),
                     empty="no label rows"))


def _interference(rep: Mapping | None) -> str:
    if rep is None:
        return ('<p class="muted">No interference report: no overlay is enabled, or no '
                "baseline run (the same run without overlays) was found.</p>")
    shared = list(rep.get("shared") or [])
    laws = rep.get("laws_ok") or {}
    facts = [["shared partitions", ", ".join(shared) or "none"],
             ["base rows identical (no sharing)", _flag(rep.get("identical_base_rows"))],
             ["exogenous draws identical", _flag(rep.get("exogenous_identical"))],
             ["first contact with a shared partition", rep.get("first_contact")],
             ["required laws hold (base run)", _flag(laws.get("base"))],
             ["required laws hold (with overlay)", _flag(laws.get("with"))]]
    if shared:
        note = (f"<p>The overlay shares state with the base through "
                f"<b>{_e(', '.join(shared))}</b>, so base outcomes may change: the changed "
                "owners below are the knock-on effects of that shared state (for example "
                "claims refused after the cohort drained it), reported here, not errors.</p>")
    else:
        note = ("<p>The overlay shares no decision-relevant state with the base: base rows "
                "must be identical with and without it.</p>")
    changed = rep.get("changed_owners") or {}
    rows = [[n, d.get("base"), d.get("with"), d.get("with", 0) - d.get("base", 0),
             changed.get(n)] for n, d in sorted((rep.get("events") or {}).items())]
    answered = []
    for part, d in sorted((rep.get("answered_differently") or {}).items()):
        answered += [[part, *k.split(" -> ", 1), n] for k, n in d.get("changed", {}).items()]
        answered += [[part, "(base run only)", "—", d.get("base_only", 0)],
                     [part, "—", "(with overlay only)", d.get("with_only", 0)]]
    requests = ""
    if shared:
        requests = ("<h3>Requests answered differently</h3>"
                    '<p class="muted">Base requests each shared partition served in both runs, '
                    "by the answer it wrote (granted ↔ rejected), matched by the causing base "
                    "row; requests found in one run only are counted apart.</p>"
                    + _table(("shared partition", "base run answer", "with overlay answer",
                              "requests"), answered, numeric=(3,),
                             empty="no base requests reached a shared partition"))
    return (_table(("check", "result"), facts) + note
            + '<p class="muted">Rows with the overlay include the rows cohort members cause '
              "on base partitions; changed owners leave members out.</p>"
            + _table(("base event", "base run rows", "with overlay rows", "Δ rows",
                      "changed owners"), rows, numeric=(1, 2, 3, 4), empty="no base events")
            + requests)


def _checks(results: Sequence[Mapping]) -> str:
    rows = []
    for r in results:
        ident = _Html(f"{_e(r.get('id'))}<br><code class=\"muted\">{_e(r.get('metric'))}</code>")
        rows.append([ident, _Html(_e(_value(r.get("value")))), _Html(_e(_ci(r.get("ci")))),
                     r.get("n_cases"), _Html(_e(_pct(r.get("censored_share")))),
                     _Html(_e(_target(r.get("target")))),
                     _status(str(r.get("status")), bool(r.get("required"))),
                     bool(r.get("required")), r.get("source"), r.get("note") or ""])
    return _table(("check", "value", "CI", "cases", "censored", "target", "status", "required",
                   "source", "note"), rows, numeric=(3, 4), empty="no checks")


def _banner(results: Sequence[Mapping]) -> str:
    bad = [r for r in results if r.get("required") and r.get("status") not in _GOOD]
    if bad:
        ids = ", ".join(f"{r.get('id')} ({r.get('status')})" for r in bad)
        return (f'<div class="banner bad">{len(bad)} required check(s) not passing: '
                f"{_e(ids)}</div>")
    n = sum(1 for r in results if r.get("required"))
    return f'<div class="banner ok">All {n} required check(s) pass.</div>'


def render(run_dir: Path, results: Sequence[Mapping], *, interference: Mapping | None,
           plan: Any) -> str:
    """The report page of the run in `run_dir`: `results` are the rows of
    `checks.stats.evaluate`, `interference` the `checks.interference.compare` report (or None),
    `plan` the run's plan (for its cohorts; None leaves the cohort section empty)."""
    run_dir = Path(run_dir)
    m = _read_json(run_dir / "manifest.json")
    st = _read_json(run_dir / "run_stats.json")
    overlays = m.get("overlays") or {}
    ov = ", ".join(f"{n}({', '.join(f'{k}={_fmt(v)}' for k, v in p.items())})"
                   for n, p in overlays.items()) or "none"
    meta = (f"pack {m.get('pack', '—')} @ {m.get('pack_revision', '—')} · profile "
            f"{m.get('profile', '—')} · seed {m.get('seed', '—')} · overlays {ov}")
    body = {
        "Counts": _counts(m),
        "Linkages": _linkages(m),
        "Transitions": _transitions(st),
        "Concentration": _concentration(run_dir),
        "Rejections": _rejections(st),
        "Cohorts": _cohorts(run_dir, m, plan),
        "Interference": _interference(interference),
        "Checks": _checks(results),
    }
    sections = "".join(_section(s, body[s]) for s in SECTIONS)
    title = f"Run report {run_dir.name}"
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_e(title)}</title><style>{_CSS}</style></head><body><main>"
            f"<h1>{_e(title)}</h1><p class=\"muted\">{_e(meta)}</p>{_banner(results)}"
            f"{sections}</main></body></html>\n")
