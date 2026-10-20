"""Avro, JSON Schema, Arrow and Markdown from schema.json, plus `--diff`.

JSON messages (replay, Kafka) carry 64-bit ids and amounts as strings, so JSON Schema types
them as integer strings; Avro keeps them as `long` and amounts as decimal(38, 0) bytes.
"""

from __future__ import annotations

import json

import pyarrow as pa

from neorisk_simkit.schema.schema_json import ltype
from neorisk_simkit.spec.types import arrow_type

INT_STRING = {"type": "string", "pattern": "^-?[0-9]+$"}


def _avro_type(c: dict, table: str) -> object:
    k = c["type"]
    t: object = {
        "i64": "long", "ref": "long", "i32": "int", "f64": "double", "bool": "boolean",
        "text": "string",
        "ts": {"type": "long", "logicalType": "timestamp-micros"},
        "amount": {"type": "bytes", "logicalType": "decimal", "precision": 38, "scale": 0},
    }.get(k)
    if k == "cat":
        t = {"type": "enum", "name": f"{table}_{c['name']}", "symbols": c["values"]}
    return ["null", t] if c["nullable"] else t


def avro(t: dict, pack: str) -> dict:
    fields = []
    for c in t["columns"]:
        f = {"name": c["name"], "type": _avro_type(c, t["name"])}
        if c["nullable"]:
            f["default"] = None
        if c.get("doc"):
            f["doc"] = c["doc"]
        fields.append(f)
    return {"type": "record", "name": t["name"], "namespace": f"datagen.{pack}",
            "doc": t.get("doc", ""), "fields": fields}


def _js_type(c: dict) -> dict:
    k = c["type"]
    if k in ("i64", "ref", "amount"):
        d = dict(INT_STRING)
    elif k == "i32":
        d = {"type": "integer"}
        if c.get("min") is not None:
            d["minimum"] = c["min"]
    elif k == "f64":
        d = {"type": "number"}
    elif k == "bool":
        d = {"type": "boolean"}
    elif k == "ts":
        d = {"type": "string", "format": "date-time"}
    elif k == "cat":
        d = {"type": "string", "enum": list(c["values"])}
    else:
        d = {"type": "string"}
    if c["nullable"]:
        d = {"anyOf": [d, {"type": "null"}]}
    if c.get("doc"):
        d["description"] = c["doc"]
    return d


def json_schema(t: dict, pack: str) -> dict:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"datagen:{pack}:{t['name']}", "title": t["name"],
            "description": t.get("doc", ""), "type": "object",
            "properties": {c["name"]: _js_type(c) for c in t["columns"]},
            "required": [c["name"] for c in t["columns"] if not c["nullable"]],
            "additionalProperties": False}


def arrow(t: dict) -> pa.Schema:
    return pa.schema([pa.field(c["name"], arrow_type(ltype(c)), nullable=c["nullable"])
                      for c in t["columns"]])


def markdown(schema: dict) -> str:
    out = [f"# {schema['pack']} data dictionary",
           f"\nschema_version {schema['schema_version']}"
           + (f" · overlays: {', '.join(schema['overlays'])}" if schema.get("overlays") else "")]
    for t in schema["tables"]:
        out.append(f"\n## {t['name']} ({t['group']})\n")
        if t.get("doc"):
            out.append(t["doc"] + "\n")
        out.append("| column | type | null | refers to | doc |\n|---|---|---|---|---|")
        for c in t["columns"]:
            typ = c["type"] + (f"({', '.join(c['values'])})" if c.get("values") else "")
            typ += f" [{c['asset']}]" if c.get("asset") else ""
            out.append(f"| {c['name']} | {typ} | {'yes' if c['nullable'] else ''} | "
                       f"{c.get('ref', '')} | {c.get('doc', '')} |")
    return "\n".join(out) + "\n"


def render(schema: dict, fmt: str, *, tables: list[str] | None = None, **sql_opts
           ) -> dict[str, str]:
    """{file stem: text} for a format: sql, avro, json-schema, arrow, markdown or json."""
    ts = [t for t in schema["tables"] if not tables or t["name"] in tables]
    if fmt == "sql":
        from neorisk_simkit.schema.sql import generate
        return generate(schema, sql_opts.pop("dialect", "postgres"), tables=tables, **sql_opts)
    if fmt == "avro":
        return {t["name"]: json.dumps(avro(t, schema["pack"]), indent=2) + "\n" for t in ts}
    if fmt == "json-schema":
        return {t["name"]: json.dumps(json_schema(t, schema["pack"]), indent=2) + "\n"
                for t in ts}
    if fmt == "arrow":
        return {t["name"]: str(arrow(t)) + "\n" for t in ts}
    if fmt == "markdown":
        sub = {**schema, "tables": ts}
        return {schema["pack"]: markdown(sub)}
    if fmt == "json":
        return {"schema": json.dumps({**schema, "tables": ts}, indent=2) + "\n"}
    raise ValueError(f"unknown format {fmt!r}")


def diff(a: dict, b: dict) -> dict:
    """Added, removed and retyped columns and tables from schema `a` to `b`. Breaking:
    anything removed or retyped, unless `b` bumped schema_version."""
    ta = {t["name"]: {c["name"]: c for c in t["columns"]} for t in a["tables"]}
    tb = {t["name"]: {c["name"]: c for c in t["columns"]} for t in b["tables"]}
    out = {"tables_added": sorted(set(tb) - set(ta)), "tables_removed": sorted(set(ta) - set(tb)),
           "columns_added": [], "columns_removed": [], "columns_retyped": []}
    for name in sorted(set(ta) & set(tb)):
        ca, cb = ta[name], tb[name]
        out["columns_added"] += [f"{name}.{c}" for c in cb if c not in ca]
        out["columns_removed"] += [f"{name}.{c}" for c in ca if c not in cb]
        for c in set(ca) & set(cb):
            x, y = ({k: v for k, v in d.items() if k != "doc"} for d in (ca[c], cb[c]))
            if x != y:
                out["columns_retyped"].append(f"{name}.{c}: {x} -> {y}")
    changed = any(out[k] for k in out)
    breaking = bool(out["tables_removed"] or out["columns_removed"] or out["columns_retyped"])
    bumped = b["schema_version"] > a["schema_version"]
    out["changed"], out["breaking"] = changed, breaking
    out["version"] = [a["schema_version"], b["schema_version"]]
    out["ok"] = not (breaking and not bumped) and not (changed and not bumped)
    return out
