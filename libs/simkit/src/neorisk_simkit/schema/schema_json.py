"""`schema/schema.json`: the canonical schema every other format is generated from.

It is built from a plan (before a run) or read from a dataset (after one), with the same
content either way.
"""

from __future__ import annotations

import json
from pathlib import Path

from neorisk_simkit.spec.plan import Plan
from neorisk_simkit.spec.types import LType, i32, i64, opt, text, ts

FORMAT = 1

LABELS = {"target_table": text(doc="The labeled entity's table"),
          "target_id": i64(doc="The labeled entity's id"), "final_label": i32(),
          "role": text(), "outcome": opt(text()), "campaign_id": opt(i64()),
          "variant": opt(text(doc="A sub-type of the role, e.g. stealth")),
          "labeled_at": ts(doc="When the simulation decided the label"),
          "label_available_at": ts(doc="When the label becomes known downstream")}


def _col(name: str, t: LType) -> dict:
    d: dict = {"name": name, "type": t.kind, "nullable": t.nullable}
    if t.values:
        d["values"] = list(t.values)
    if t.target:
        d["ref"] = t.target
    if t.asset:
        d["asset"] = t.asset
    if t.minimum is not None:
        d["min"] = t.minimum
    if t.doc:
        d["doc"] = t.doc
    return d


def ltype(d: dict) -> LType:
    return LType(d["type"], d["nullable"], tuple(d.get("values", ())), d.get("ref"),
                 d.get("asset"), d.get("min"), d.get("doc", ""))


def build(plan: Plan) -> dict:
    tables = []
    for group, ts_ in (("event", plan.events), ("entity", plan.entities)):
        for t in ts_.values():
            tables.append({"name": t.name, "group": group, "doc": t.doc,
                           **({"key": t.key} if t.key else {}),
                           "columns": [_col(c, lt) for c, lt in t.columns().items()]})
    tables.append({"name": "labels", "group": "label",
                   "doc": "Hidden labels: never replayed unless asked, never in events",
                   "columns": [_col(c, lt) for c, lt in LABELS.items()]})
    return {"format": FORMAT, "pack": plan.name, "schema_version": plan.pack.schema_version,
            "overlays": [o.name for o in plan.overlays],
            "actions": [{"id": a.id, "kind": a.kind, "process": a.process, "name": a.name}
                        for a in plan.actions],
            "tables": tables}


def dumps(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=False) + "\n"


def load(path: str | Path) -> dict:
    """From a dataset directory, a schema.json path, or a pack project (via its plan)."""
    p = Path(path)
    if p.is_dir() and (p / "schema" / "schema.json").exists():
        p = p / "schema" / "schema.json"
    if p.suffix == ".json":
        return json.loads(p.read_text())
    from neorisk_simkit.project import load_project
    return build(load_project(p).plan())


def table_columns(schema: dict, name: str) -> dict[str, LType]:
    for t in schema["tables"]:
        if t["name"] == name:
            return {c["name"]: ltype(c) for c in t["columns"]}
    raise KeyError(name)
