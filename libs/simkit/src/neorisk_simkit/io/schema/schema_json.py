"""`schema/schema.json`: every table, column, type, nullability, refs and docs (spec section 14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neorisk_simkit.io.seal import ENTITY_HEAD, HISTORY_HEAD
from neorisk_simkit.spec.types import LType, arrow_type, i32, i64, text, ts

_COMMON_DOCS = {
    "event_id": "Public ID of the event.",
    "event_type": "Name of the event type.",
    "event_time": "Event time, UTC, microseconds.",
    "lamport": "Lamport clock of the emitting partition at commit.",
    "partition_id": "Partition that emitted the event.",
    "seq": "Record sequence number within the partition.",
    "cause_id": "ID of the causing event (null in S1).",
    "action_id": "Process that emitted the event.",
}
_HISTORY_DOCS = {
    "entity_id": "Public ID of the changed entity.",
    "valid_from": "Time from which the new values hold.",
    "lamport": _COMMON_DOCS["lamport"],
    "partition_id": _COMMON_DOCS["partition_id"],
    "seq": _COMMON_DOCS["seq"],
}
_ENTITY_DOCS = {
    "id": "Public ID of the entity.",
    "created_at": "Creation time, UTC, microseconds.",
    "origin": "How the row came to be: static, initial, arrival or created.",
}


def _column(name: str, lt: LType, doc: str = "") -> dict[str, Any]:
    return {"name": name, "type": lt.kind, "nullable": lt.nullable,
            "arrow": str(arrow_type(lt)), "ref": lt.target,
            "values": list(lt.values) if lt.kind == "cat" else None, "asset": lt.asset,
            "quantum": lt.quantum if lt.kind == "amount" else None, "minimum": lt.minimum,
            "doc": doc}


def _head(names: tuple[str, ...], types: dict[str, LType], docs: dict[str, str]):
    return [_column(n, types[n], docs[n]) for n in names]


def schema_document(plan: Any) -> dict[str, Any]:
    """The schema of every table of a run: events (common columns first), entities (`id`,
    `created_at`, `origin` first) and history groups (ordering columns first)."""
    from neorisk_simkit.spec.types import COMMON_COLUMNS

    tables: list[dict[str, Any]] = []
    for e in plan.events:
        cols = [_column(c.name, c.ltype, _COMMON_DOCS.get(c.name, "") if i < len(COMMON_COLUMNS)
                        else "") for i, c in enumerate(e.cols)]
        tables.append({"name": e.name, "kind": "event", "doc": e.doc, "columns": cols})
    entity_types = {"id": i64(), "created_at": ts(), "origin": text()}
    for t in plan.tables:
        cols = _head(ENTITY_HEAD, entity_types, _ENTITY_DOCS)
        cols += [_column(c.name, c.ltype) for c in t.cols]
        tables.append({"name": t.name, "kind": "entity", "doc": t.doc, "columns": cols})
    hist_types = {"entity_id": i64(), "valid_from": ts(), "lamport": i64(),
                  "partition_id": i64(), "seq": i32()}
    for g in plan.change_groups:
        cols = _head(HISTORY_HEAD, hist_types, _HISTORY_DOCS)
        cols += [_column(c.name, c.ltype) for c in g.cols]
        tables.append({"name": g.name, "kind": "history",
                       "doc": f"Typed changes of {g.table}.", "columns": cols})
    return {"pack": plan.pack, "revision": plan.revision, "schema_version": plan.schema_version,
            "tables": tables}


def write_schema(run_dir: Path, plan: Any) -> Path:
    path = Path(run_dir) / "schema" / "schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema_document(plan), sort_keys=True, indent=2) + "\n")
    return path


def load_schema(dataset_dir: Path) -> dict[str, Any]:
    return json.loads((Path(dataset_dir) / "schema" / "schema.json").read_text())
