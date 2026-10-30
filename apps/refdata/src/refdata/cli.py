"""refdata: real tables as simkit event logs, rebuilt and compared exactly.

    refdata fetch [--dest DIR] [--force]
    refdata ingest PROJECT [--db SRC] [--out DIR] [--force]

Exit codes: 0 success, 1 a round trip or comparison differs, 2 usage error, missing source or
refusal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REF = Path("data/ref")


def _err(msg: str, code: int = 2) -> int:
    print(f"refdata: {msg}", file=sys.stderr)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refdata")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download the Spider2-lite SQLite databases")
    f.add_argument("--dest", default=None, help="default: data/spider2")
    f.add_argument("--force", action="store_true", help="download even if the files exist")
    i = sub.add_parser("ingest", help="source tables → a simkit dataset (specs/ingest.sql)")
    i.add_argument("project")
    i.add_argument("--db", default=None, help="default: data/spider2/<source.toml file>")
    i.add_argument("--out", default=None, help="default: data/ref/<project>")
    i.add_argument("--force", action="store_true", help="overwrite an existing dataset")
    return parser


def _db(project: Path, db: str | None) -> Path:
    from refdata.fetch import DATA
    from refdata.source import load_source
    return Path(db) if db else DATA / load_source(project).file


def _ingest(args) -> int:
    from refdata.ingest import IngestError, ingest
    project = Path(args.project)
    out = Path(args.out) if args.out else REF / project.name
    try:
        ingest(project, _db(project, args.db), out, force=args.force)
    except (FileNotFoundError, FileExistsError) as e:
        return _err(str(e))
    except IngestError as e:
        return _err(str(e), 1)
    print(json.dumps({"dataset": str(out)}))
    return 0


def _fetch(args) -> int:
    from refdata import fetch
    dest = Path(args.dest) if args.dest else fetch.DATA
    try:
        files = fetch.fetch(dest, force=args.force)
    except (OSError, ValueError) as e:
        return _err(str(e), 1)
    print(json.dumps({"dest": str(dest), "files": len(files)}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"fetch": _fetch, "ingest": _ingest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
