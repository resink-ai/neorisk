"""SQL DDL from schema.json, in six dialects.

| logical  | postgres         | duckdb        | bigquery   | snowflake    | clickhouse               | spark          |
|----------|------------------|---------------|------------|--------------|--------------------------|----------------|
| i64, ref | BIGINT           | BIGINT        | INT64      | BIGINT       | Int64                    | BIGINT         |
| i32      | INTEGER          | INTEGER       | INT64      | INTEGER      | Int32                    | INT            |
| amount   | NUMERIC(38,0)    | DECIMAL(38,0) | BIGNUMERIC | NUMBER(38,0) | Decimal(38,0)            | DECIMAL(38,0)  |
| ts       | TIMESTAMPTZ      | TIMESTAMPTZ   | TIMESTAMP  | TIMESTAMP_TZ | DateTime64(6,'UTC')      | TIMESTAMP      |
| cat      | TEXT + CHECK     | ENUM(...)     | STRING     | VARCHAR      | LowCardinality(String)   | STRING         |
| text     | TEXT             | VARCHAR       | STRING     | VARCHAR      | String                   | STRING         |
| bool     | BOOLEAN          | BOOLEAN       | BOOL       | BOOLEAN      | Bool                     | BOOLEAN        |
| f64      | DOUBLE PRECISION | DOUBLE        | FLOAT64    | FLOAT        | Float64                  | DOUBLE         |
"""

from __future__ import annotations

DIALECTS = ("postgres", "duckdb", "bigquery", "snowflake", "clickhouse", "spark")
_T = {
    "postgres": {"i64": "BIGINT", "ref": "BIGINT", "i32": "INTEGER", "amount": "NUMERIC(38,0)",
                 "ts": "TIMESTAMPTZ", "cat": "TEXT", "text": "TEXT", "bool": "BOOLEAN",
                 "f64": "DOUBLE PRECISION"},
    "duckdb": {"i64": "BIGINT", "ref": "BIGINT", "i32": "INTEGER", "amount": "DECIMAL(38,0)",
               "ts": "TIMESTAMPTZ", "cat": "ENUM", "text": "VARCHAR", "bool": "BOOLEAN",
               "f64": "DOUBLE"},
    "bigquery": {"i64": "INT64", "ref": "INT64", "i32": "INT64", "amount": "BIGNUMERIC",
                 "ts": "TIMESTAMP", "cat": "STRING", "text": "STRING", "bool": "BOOL",
                 "f64": "FLOAT64"},
    "snowflake": {"i64": "BIGINT", "ref": "BIGINT", "i32": "INTEGER", "amount": "NUMBER(38,0)",
                  "ts": "TIMESTAMP_TZ", "cat": "VARCHAR", "text": "VARCHAR", "bool": "BOOLEAN",
                  "f64": "FLOAT"},
    "clickhouse": {"i64": "Int64", "ref": "Int64", "i32": "Int32", "amount": "Decimal(38,0)",
                   "ts": "DateTime64(6,'UTC')", "cat": "LowCardinality(String)",
                   "text": "String", "bool": "Bool", "f64": "Float64"},
    "spark": {"i64": "BIGINT", "ref": "BIGINT", "i32": "INT", "amount": "DECIMAL(38,0)",
              "ts": "TIMESTAMP", "cat": "STRING", "text": "STRING", "bool": "BOOLEAN",
              "f64": "DOUBLE"},
}
GROUP_DIR = {"event": "events", "entity": "entities", "label": "labels"}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _type(c: dict, dialect: str) -> str:
    t = _T[dialect][c["type"]]
    if dialect == "duckdb" and c["type"] == "cat":
        t = "ENUM(" + ", ".join(_q(v) for v in c["values"]) + ")"
    if dialect == "clickhouse" and c["nullable"]:
        t = f"Nullable({t})"
    return t


def _column(c: dict, dialect: str, pk: str | None) -> str:
    parts = [f"    {c['name']:<20} {_type(c, dialect)}"]
    if not c["nullable"] and dialect not in ("clickhouse",):
        parts.append("NOT NULL")
    if c["name"] == pk and dialect in ("postgres", "duckdb", "snowflake"):
        parts.append("PRIMARY KEY")
    checks = []
    if dialect == "postgres" and c["type"] == "cat":
        checks.append(f"{c['name']} IN (" + ", ".join(_q(v) for v in c["values"]) + ")")
    if dialect in ("postgres", "duckdb") and c.get("min") is not None:
        checks.append(f"{c['name']} >= {c['min']}")
    if checks:
        parts.append("CHECK (" + " AND ".join(checks) + ")")
    if dialect == "bigquery" and c.get("doc"):
        parts.append(f"OPTIONS(description={_q(c['doc'])})")
    if dialect in ("snowflake", "spark", "clickhouse") and c.get("doc"):
        parts.append(f"COMMENT {_q(c['doc'])}")
    return " ".join(parts)


def _pk(t: dict) -> str | None:
    return "event_id" if t["group"] == "event" else t.get("key")


def table_ddl(t: dict, dialect: str, *, keys: dict[str, str], with_fks: bool = False,
              dataset: str | None = None) -> str:
    pk = _pk(t)
    cols = [_column(c, dialect, pk) for c in t["columns"]]
    if with_fks and dialect in ("postgres", "duckdb", "snowflake"):
        cols += [f"    FOREIGN KEY ({c['name']}) REFERENCES {c['ref']} ({keys[c['ref']]})"
                 for c in t["columns"]
                 if c["type"] == "ref" and c["ref"] in keys and c["ref"] != t["name"]]
    name = f"{dataset}.{t['name']}" if dataset and dialect == "bigquery" else t["name"]
    out = [f"CREATE TABLE {name} (", ",\n".join(cols), ")"]
    if dialect == "clickhouse":
        out.append(f"ENGINE = MergeTree ORDER BY ({pk or 'tuple()'})")
    if t.get("doc") and dialect in ("bigquery",):
        out.append(f"OPTIONS(description={_q(t['doc'])})")
    if t.get("doc") and dialect in ("snowflake", "spark", "clickhouse"):
        out.append(f"COMMENT {_q(t['doc'])}")
    ddl = "\n".join(out) + ";"
    if t.get("doc") and dialect == "postgres":
        ddl += f"\nCOMMENT ON TABLE {t['name']} IS {_q(t['doc'])};"
    if t["group"] == "event" and dialect in ("postgres", "duckdb"):
        ddl += f"\nCREATE INDEX {t['name']}_order ON {t['name']} (event_time, seq);"
    return ddl


def load_stmt(t: dict, dialect: str, root: str) -> str:
    path = f"{root}/{GROUP_DIR[t['group']]}/{t['name']}.parquet"
    return {
        "postgres": f"-- postgres cannot read parquet; convert first, then:\n"
                    f"-- COPY {t['name']} FROM '{path[:-8]}.csv' WITH (FORMAT csv, HEADER);",
        "duckdb": f"INSERT INTO {t['name']} SELECT * FROM read_parquet('{path}');",
        "bigquery": f"LOAD DATA INTO {t['name']} FROM FILES (format = 'PARQUET', "
                    f"uris = ['{path}']);",
        "snowflake": f"COPY INTO {t['name']} FROM @datagen_stage/{GROUP_DIR[t['group']]}/"
                     f"{t['name']}.parquet FILE_FORMAT = (TYPE = PARQUET) "
                     f"MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;",
        "clickhouse": f"INSERT INTO {t['name']} SELECT * FROM file('{path}', Parquet);",
        "spark": f"INSERT INTO {t['name']} SELECT * FROM parquet.`{path}`;",
    }[dialect]


def unified_view(schema: dict) -> str:
    common = [c["name"] for c in next(t for t in schema["tables"]
                                      if t["group"] == "event")["columns"][:7]]
    sel = [f"SELECT {', '.join(common)} FROM {t['name']}" for t in schema["tables"]
           if t["group"] == "event"]
    return "CREATE VIEW all_events AS\n" + "\nUNION ALL ".join(sel) + ";"


def ordered(schema: dict) -> list[dict]:
    """Entity tables before the tables that reference them (so the DDL runs top to bottom),
    then events and labels."""
    ents = {t["name"]: t for t in schema["tables"] if t["group"] == "entity"}
    done: list[str] = []

    def visit(name: str, seen: frozenset = frozenset()) -> None:
        if name in done or name in seen:
            return
        for c in ents[name]["columns"]:
            if c["type"] == "ref" and c["ref"] in ents and c["ref"] != name:
                visit(c["ref"], seen | {name})
        done.append(name)
    for n in ents:
        visit(n)
    return [ents[n] for n in done] + [t for t in schema["tables"] if t["group"] != "entity"]


def generate(schema: dict, dialect: str, *, tables: list[str] | None = None,
             with_fks: bool = False, load: str | None = None, unified: bool = False,
             dataset: str | None = None) -> dict[str, str]:
    """One DDL text per table (plus `all_events` with `unified`)."""
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect!r}; have {', '.join(DIALECTS)}")
    keys = {t["name"]: t["key"] for t in schema["tables"] if t["group"] == "entity"}
    head = (f"-- generated by datagen schema · pack {schema['pack']} · "
            f"schema_version {schema['schema_version']} · {dialect}\n")
    out = {}
    for t in ordered(schema):
        if tables and t["name"] not in tables:
            continue
        ddl = table_ddl(t, dialect, keys=keys, with_fks=with_fks, dataset=dataset)
        if load:
            ddl += "\n" + load_stmt(t, dialect, load)
        out[t["name"]] = head + ddl + "\n"
    if unified:
        out["all_events"] = head + unified_view(schema) + "\n"
    return out
