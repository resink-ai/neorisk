"""`datagen schema`: DDL or JSON schema from a project folder or a dataset folder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FORMATS = ("sql", "json")


def cmd_schema(args: argparse.Namespace) -> int:
    from datagen.run_cmds import overlay_list
    from neorisk_simkit.io.schema.schema_json import load_schema, schema_document
    from neorisk_simkit.io.schema.sql import DIALECTS, SqlError, render_sql
    from neorisk_simkit.spec.project import ProjectError, load_project, resolve_run

    if args.format not in _FORMATS:
        print(f"{args.format} arrives in M4", file=sys.stderr)
        return 2
    if args.dialect not in DIALECTS:
        print(f"{args.dialect} arrives in M4", file=sys.stderr)
        return 2
    target = Path(args.target)
    try:
        if (target / "manifest.json").is_file():
            doc = load_schema(target)
        else:
            project = load_project(target)
            doc = schema_document(resolve_run(project, args.profile, args.set,
                                              overlays=overlay_list(project, args.profile,
                                                                    args)).plan)
        if args.format == "json":
            print(json.dumps(doc, sort_keys=True, indent=2))
            return 0
        # D95: DDL holds the base tables, plus the tables of overlays named with --overlay
        named = set(args.overlay or [])
        doc = {**doc, "tables": [t for t in doc["tables"]
                                 if t.get("overlay") is None or t["overlay"] in named]}
        tables = [t for t in args.tables.split(",") if t] if args.tables else None
        sql = render_sql(doc, args.dialect, tables=tables, with_fks=args.with_fks)
    except (ProjectError, SqlError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 2
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, ddl in sql.items():
            (out / f"{name}.sql").write_text(ddl)
    else:
        print("\n".join(sql.values()), end="")
    return 0
