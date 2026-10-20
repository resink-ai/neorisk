"""datagen schema SOURCE [--overlay NAME]... --format FMT [--dialect D] [--tables a,b]
                    [--with-fks] [--load PATH] [--unified-view] [--out DIR | --single-file F]
datagen schema --diff A B

SOURCE is a project folder (schema from the pack) or a dataset folder (its schema.json); the
output is the same. FMT: sql, avro, json-schema, arrow, markdown, json. Without --out the
text goes to stdout. --diff exits 1 when a column changes without a schema_version bump.
"""

from __future__ import annotations

import json
from pathlib import Path

EXT = {"sql": "sql", "avro": "avsc", "json-schema": "schema.json", "arrow": "txt",
       "markdown": "md", "json": "json"}


def add_parser(sub) -> None:
    s = sub.add_parser("schema", help="generate SQL / Avro / JSON Schema / Arrow / Markdown")
    s.add_argument("source", nargs="?", help="project or dataset folder")
    s.add_argument("--overlay", action="append", default=[])
    s.add_argument("--format", default="sql", choices=list(EXT))
    s.add_argument("--dialect", default="postgres")
    s.add_argument("--tables", default=None, help="comma list of tables")
    s.add_argument("--with-fks", action="store_true", help="foreign keys from ref columns")
    s.add_argument("--load", default=None, metavar="DATASET",
                   help="add load statements reading this dataset's files")
    s.add_argument("--unified-view", action="store_true", help="an all_events view")
    s.add_argument("--out", default=None, help="one file per table in this folder")
    s.add_argument("--single-file", default=None, help="everything in one file")
    s.add_argument("--diff", nargs=2, metavar=("A", "B"), default=None)


def _schema(source: str, overlays: list[str]) -> dict:
    from neorisk_simkit.project import load_project
    from neorisk_simkit.schema import schema_json
    p = Path(source)
    if (p / "schema" / "schema.json").exists() or p.suffix == ".json":
        return schema_json.load(p)
    pr = load_project(p)
    s = pr.settings(None, [], overlays)
    return schema_json.build(pr.plan(s.overlays))


def run(args) -> int:
    from datagen.cli import _err
    from neorisk_simkit.schema.formats import diff, render
    if args.diff:
        d = diff(_schema(args.diff[0], []), _schema(args.diff[1], []))
        print(json.dumps(d, indent=2))
        return 0 if d["ok"] else 1
    if not args.source:
        return _err("schema: pass a project or dataset folder (or --diff A B)")
    opts = {}
    if args.format == "sql":
        opts = {"dialect": args.dialect, "with_fks": args.with_fks, "load": args.load,
                "unified": args.unified_view}
    tables = args.tables.split(",") if args.tables else None
    try:
        files = render(_schema(args.source, args.overlay), args.format, tables=tables, **opts)
    except ValueError as e:
        return _err(str(e))
    if args.single_file:
        Path(args.single_file).write_text("\n".join(files.values()))
    elif args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / f"{name}.{EXT[args.format]}").write_text(text)
    else:
        print("\n".join(files.values()), end="")
    return 0
