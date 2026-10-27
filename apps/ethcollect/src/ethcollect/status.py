"""A plain-text report: connectors and their last run, table sizes, and toy-sample checks."""

from __future__ import annotations

import json
from pathlib import Path

from ethcollect import connectors, tables


def last_runs(root: Path) -> dict[str, dict]:
    runs: dict[str, dict] = {}
    for f in sorted((root / "runs").glob("*.json")):
        rec = json.loads(f.read_text())
        runs[rec["source"]] = rec  # sorted by timestamp, so the last one wins
    return runs


def report(root: Path) -> str:
    root = Path(root)
    runs = last_runs(root)
    lines = [f"eth-collect status for {root}", "", "connectors:"]
    for source in connectors.SOURCES:
        m = connectors.load(source)
        r = runs.get(source)
        if r is None:
            state = "never run"
        else:
            counts = ", ".join(f"{k} {r[k]}" for k in ("labels", "transfers", "addresses")
                               if k in r)
            state = f"{'ok' if r.get('ok') else 'FAILED'} {counts} ({r.get('seconds')}s)"
            if r.get("error"):
                state += f" error: {r['error'][:80]}"
        lines.append(f"  {source:<20}{m.KIND:<7}{state}")

    lines += ["", "tables (all sources, de-duplicated):"]
    for t in ("labels", "transfers", "addresses"):
        lines.append(f"  {t:<10}{tables.load(root, t).height:>9} rows")
    labels = tables.load(root, "labels")
    if labels.height:
        lines += ["", "labels by kind and source:"]
        sql = ("select label_kind, source, count(*) n, sum(date_known::int) dated from labels "
               "group by all order by label_kind, n desc")
        con = tables.db()
        con.register("labels", labels)
        for kind, source, n, dated in con.sql(sql).fetchall():
            lines.append(f"  {kind:<12}{source:<20}{n:>7}  ({dated} with a date)")

    toy = root / "samples" / "toy"
    if (toy / "manifest.json").exists():
        lines += ["", "toy sample:"] + [f"  {ln}" for ln in toy_checks(toy)]
    return "\n".join(lines)


def toy_checks(toy: Path) -> list[str]:
    m = json.loads((toy / "manifest.json").read_text())
    tr, ad, lb = (f"read_parquet('{toy / f}.parquet')" for f in ("transfers", "addresses",
                                                                    "labels"))
    q = tables.db().sql
    lo, hi = q(f"select min(ts)::date, max(ts)::date from {tr}").fetchone()
    per = q(f"""select count(*), median(n), max(n) from (
                select a, count(*) n from (select from_address a from {tr}
                union all select to_address from {tr})
                where a in (select address from {ad} where sample_reason in ('seed','random'))
                group by a)""").fetchone()
    reasons = dict(q(f"select sample_reason, count(*) from {ad} group by 1").fetchall())
    contracts = q(f"select count(*) filter (is_contract), count(*) filter "
                  f"(is_contract is null) from {ad}").fetchone()
    labeled = q(f"""select count(distinct a.address) from {ad} a join {lb} l using (address)
                    where a.sample_reason in ('seed','random') and l.is_risk""").fetchone()[0]
    labeled_bg = q(f"""select count(distinct a.address) from {ad} a join {lb} l using (address)
                       where a.sample_reason = 'random' and l.is_risk""").fetchone()[0]
    late = q(f"""select count(*) from {tr} t join (select address, min(observed_at) d
                 from {lb} where is_risk and date_known group by 1) l
                 on l.address in (t.from_address, t.to_address) where t.ts::date > l.d
             """).fetchone()[0]
    kinds = q(f"select kind, count(*) from {tr} group by 1 order by 2 desc").fetchall()
    return [
        (f"built {m['built_at'][:19]}, seed {m['seed']}, window {m['window'][0]} to "
         f"{m['window'][1]}, history from {m['history_source']}, cap {m['cap']}"),
        f"addresses: {reasons}; contracts {contracts[0]}, unknown {contracts[1]}",
        (f"transfers: {sum(n for _, n in kinds)} ({', '.join(f'{k} {n}' for k, n in kinds)}), "
         f"dated {lo} to {hi}"),
        f"per sampled address: {per[0]} addresses with transfers, median {per[1]}, max {per[2]}",
        (f"risk-labeled sampled addresses: {labeled} (of them in the random background: "
         f"{labeled_bg})"),
        f"transfers after a label's observed_at: {late} (the model must drop these)",
    ]
