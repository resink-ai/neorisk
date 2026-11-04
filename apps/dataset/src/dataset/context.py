"""The counted sections of a dataset's CONTEXT.md, rendered from its built version.

Event and table counts come from the manifest and the schema files, never by hand. The prose
sections (what this is, raw data, how the log was made, times set by rule, extend) are written
by the dataset's author around them.
"""

from __future__ import annotations

import json
from pathlib import Path

from dataset.config import DatasetConfig

ENVELOPE = ("event_id", "sim_seq", "partition_id", "cause_id", "action_id")


def _log_counts(root: Path) -> dict[str, int]:
    import duckdb
    return dict(duckdb.sql(f"SELECT event_type, count(*) FROM read_parquet('{root}/log/*.parquet') "
                           "GROUP BY 1").fetchall())


def _intro(version: str, kind: str, events: int, tables: int, queries: int) -> str:
    log = f"{events:,} event" + ("" if events == 1 else "s")
    out = "the source table" if tables == 1 else f"the {tables} source tables"
    text = (f"Version `{version}`, kind `{kind}`. The input is one ordered event log of {log}; "
            f"the output is {out}, rebuilt exactly")
    if queries:
        text += (", and the answer to 1 saved Spider 2.0 question" if queries == 1 else
                 f", and the answers to {queries} saved Spider 2.0 questions")
    return text + "."


def render(cfg: DatasetConfig, root: Path) -> str:
    events = json.loads((root / "schema" / "events.json").read_text())["events"]
    results = json.loads((root / "schema" / "results.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    counts = _log_counts(root)
    tables, queries = results["tables"], sorted(results["queries"])
    out = [_intro(cfg.version, cfg.kind, manifest["counts"]["log"], len(tables), len(queries)), "",
           "## Event catalogue", "", "| Event | Kind | Rows | Payload fields |", "|---|---|---:|---|"]
    for e in events:
        kind = "entity" if e["kind"] == "entity_created" else "business"
        fields = [f["name"] for f in e["fields"] if kind == "entity" or f["name"] not in ENVELOPE]
        out.append(f"| `{e['name']}` | {kind} | {counts.get(e['name'], 0):,} | "
                   + ", ".join(f"`{f}`" for f in fields) + " |")
    out += ["", "## Expected output", "",
            "| Table | Rows | Columns | Mixed columns |", "|---|---:|---:|---|"]
    for t, m in tables.items():
        mixed = ", ".join(f"`{c}`" for c in m["mixed"]) or "none"
        out.append(f"| `{t}` | {manifest['counts'][f'results/{t}']:,} | {len(m['columns'])} | "
                   f"{mixed} |")
    if queries:
        out += ["", "`expected/queries/` holds the answers of the saved questions ("
                + ", ".join(f"`{q}`" for q in queries) + "), computed on the source."]
    out += ["", "## Regenerate", "", "```bash",
            "uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/",
            (f"uv run dataset build {cfg.name}             # → $NEORISK_DATA_ROOT/{cfg.name}/"
             f"{cfg.version}/ (default data/datasets/)"),
            f"uv run dataset verify {cfg.name}            # exit 0 = every table and answer matches",
            "```", ""]
    return "\n".join(out)
