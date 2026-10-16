"""SQL DDL (Postgres, DuckDB) from a schema document (spec section 14, decision D24)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_PLAIN = re.compile(r"[a-z_][a-z0-9_]*")
_PG_MAX_IDENT = 63
DIALECTS = ("postgres", "duckdb")

# Static keyword set (the library cannot import duckdb at runtime): every DuckDB 1.5.6 keyword
# not categorised 'unreserved' in duckdb_keywords(), plus the PostgreSQL reserved and
# reserved-(can be function or type) keywords. A test compares it with the installed DuckDB.
RESERVED = frozenset({
    "all", "analyse", "analyze", "and", "anti", "any", "array", "as", "asc", "asof",
    "asymmetric", "at", "authorization", "between", "bigint", "binary", "bit", "boolean",
    "both", "by", "case", "cast", "char", "character", "check", "coalesce", "collate",
    "collation", "column", "columns", "concurrently", "constraint", "create", "cross",
    "current_catalog", "current_date", "current_role", "current_schema", "current_time",
    "current_timestamp", "current_user", "dec", "decimal", "default", "deferrable", "desc",
    "describe", "distinct", "do", "else", "end", "except", "exists", "extract", "false",
    "fetch", "float", "for", "foreign", "freeze", "from", "full", "generated", "glob", "grant",
    "group", "grouping", "grouping_id", "having", "ilike", "in", "initially", "inner", "inout",
    "int", "integer", "intersect", "interval", "into", "is", "isnull", "join", "lambda",
    "lateral", "leading", "left", "like", "limit", "localtime", "localtimestamp", "map",
    "national", "natural", "nchar", "none", "not", "notnull", "null", "nullif", "numeric",
    "offset", "on", "only", "or", "order", "out", "outer", "overlaps", "overlay", "pivot",
    "pivot_longer", "pivot_wider", "placing", "position", "positional", "precision", "primary",
    "qualify", "real", "references", "returning", "right", "row", "select", "semi",
    "session_user", "setof", "show", "similar", "smallint", "some", "struct", "substring",
    "summarize", "symmetric", "system_user", "table", "tablesample", "then", "time",
    "timestamp", "to", "trailing", "treat", "trim", "true", "try_cast", "union", "unique",
    "unpack", "unpivot", "user", "using", "values", "varchar", "variadic", "verbose", "when",
    "where", "window", "with", "xmlattributes", "xmlconcat", "xmlelement", "xmlexists",
    "xmlforest", "xmlnamespaces", "xmlparse", "xmlpi", "xmlroot", "xmlserialize", "xmltable",
})
_TYPES = {
    "postgres": {"i16": "SMALLINT", "i32": "INTEGER", "i64": "BIGINT", "ref": "BIGINT",
                 "amount": "NUMERIC(38,0)", "ts": "TIMESTAMPTZ", "text": "TEXT",
                 "bool": "BOOLEAN", "f64": "DOUBLE PRECISION"},
    "duckdb": {"i16": "SMALLINT", "i32": "INTEGER", "i64": "BIGINT", "ref": "BIGINT",
               "amount": "DECIMAL(38,0)", "ts": "TIMESTAMPTZ", "text": "VARCHAR",
               "bool": "BOOLEAN", "f64": "DOUBLE"},
}
_MINOR = {"USD": "cents", "EUR": "cents", "GBP": "pence"}


class SqlError(Exception):
    pass


def quote_ident(name: str, dialect: str) -> str:
    if name in RESERVED or not _PLAIN.fullmatch(name):
        return '"' + name.replace('"', '""') + '"'
    return name


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _column_line(table: dict[str, Any], col: dict[str, Any], dialect: str,
                 entity_tables: set[str], with_fks: bool) -> tuple[str, str]:
    """(definition, trailing comment) of one column."""
    name, kind = col["name"], col["type"]
    q = quote_ident(name, dialect)
    cons: list[str] = []
    if kind == "cat":
        values = ", ".join(_lit(v) for v in col["values"])
        if dialect == "duckdb":
            sqltype = f"ENUM({values})"
        else:
            sqltype = "TEXT"
    else:
        sqltype = _TYPES[dialect][kind]
    if not col["nullable"]:
        cons.append("NOT NULL")
    if (table["kind"] == "event" and name == "event_id") or (
            table["kind"] == "entity" and name == "id"):
        cons.append("PRIMARY KEY")
    if table["kind"] == "event" and name == "event_type":
        cons.append(f"CHECK (event_type = {_lit(table['name'])})")
    if col.get("minimum") is not None:
        cons.append(f"CHECK ({q} >= {col['minimum']})")
    if kind == "cat" and dialect == "postgres":
        cons.append(f"CHECK ({q} IN ({', '.join(_lit(v) for v in col['values'])}))")
    if with_fks and kind == "ref" and col.get("ref") in entity_tables:
        cons.append(f"REFERENCES {quote_ident(col['ref'], dialect)} (id)")
    comment = ""
    if kind == "amount":
        comment = f"-- {col['asset']} minor units"
        if col["asset"] in _MINOR:
            comment += f" ({_MINOR[col['asset']]})"
    return f"    {q:<14}{sqltype:<12} {' '.join(cons)}".rstrip(), comment


def _render_table(doc: dict[str, Any], table: dict[str, Any], dialect: str,
                  entity_tables: set[str], with_fks: bool) -> str:
    t = quote_ident(table["name"], dialect)
    header = (f"-- generated by datagen schema · pack {doc['pack']} @ {doc['revision']}"
              f" · schema_version {doc['schema_version']}")
    lines = [header, f"CREATE TABLE {t} ("]
    cols = table["columns"]
    for i, col in enumerate(cols):
        text, comment = _column_line(table, col, dialect, entity_tables, with_fks)
        if i < len(cols) - 1:
            text += ","
        if comment:
            text += "   " + comment
        lines.append(text)
    lines.append(");")
    if table.get("doc"):
        lines.append(f"COMMENT ON TABLE {t} IS {_lit(table['doc'])};")
    if table["kind"] == "event":
        lines.append(f"CREATE INDEX {quote_ident(table['name'] + '_time', dialect)} "
                     f"ON {t} (event_time, lamport);")
    return "\n".join(lines) + "\n"


def _check_lengths(doc: dict[str, Any], rendered: dict[str, str]) -> None:
    """Postgres truncates identifiers beyond 63 bytes: refuse instead."""
    for t in doc["tables"]:
        if t["name"] not in rendered:
            continue
        names = [t["name"], *(c["name"] for c in t["columns"])]
        if t["kind"] == "event":
            names.append(t["name"] + "_time")
        for n in names:
            if len(n.encode()) > _PG_MAX_IDENT:
                raise SqlError(f"identifier {n!r} exceeds Postgres' {_PG_MAX_IDENT}-byte limit")


def render_sql(doc: dict[str, Any], dialect: str, tables: Sequence[str] | None = None,
               with_fks: bool = False) -> dict[str, str]:
    """Table name -> DDL text, in schema order."""
    if dialect not in DIALECTS:
        raise SqlError(f"dialect {dialect!r} arrives in M4")
    known = {t["name"] for t in doc["tables"]}
    for name in tables or ():
        if name not in known:
            raise SqlError(f"unknown table {name!r}")
    entity_tables = {t["name"] for t in doc["tables"] if t["kind"] == "entity"}
    out = {t["name"]: _render_table(doc, t, dialect, entity_tables, with_fks)
           for t in doc["tables"] if tables is None or t["name"] in tables}
    if dialect == "postgres":
        _check_lengths(doc, out)
    return out
