"""refdata: real tables as simkit event logs, rebuilt and compared exactly.

    refdata fetch [--dest DIR] [--force]
    refdata ingest PROJECT [--db SRC] [--out DIR] [--force]
    refdata rebuild LOG --project P [--db SRC] [--out FILE] [--force]
    refdata compare SRC REBUILT --project P [--json FILE]
    refdata roundtrip PROJECT [--db SRC] [--out-dir DIR] [--force]

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
    r = sub.add_parser("rebuild", help="an event log → the source tables (specs/build.sql)")
    r.add_argument("log", help="a directory holding log/ and schema/events.json")
    r.add_argument("--project", required=True)
    r.add_argument("--db", default=None, help="source, for its DDL; default: data/spider2/...")
    r.add_argument("--out", default=None, help="default: data/ref/<project>.rebuilt.sqlite")
    r.add_argument("--force", action="store_true", help="overwrite an existing file")
    c = sub.add_parser("compare", help="source vs rebuilt: tables and saved queries")
    c.add_argument("src")
    c.add_argument("rebuilt")
    c.add_argument("--project", required=True)
    c.add_argument("--json", default=None, help="write the full report here")
    t = sub.add_parser("roundtrip", help="ingest → rebuild → compare")
    t.add_argument("project")
    t.add_argument("--db", default=None, help="default: data/spider2/<source.toml file>")
    t.add_argument("--out-dir", default=None, help="default: data/ref")
    t.add_argument("--force", action="store_true", help="overwrite earlier outputs")
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


def _rebuild(args) -> int:
    from refdata.rebuild import rebuild
    project = Path(args.project)
    out = Path(args.out) if args.out else REF / f"{project.name}.rebuilt.sqlite"
    try:
        rebuild(Path(args.log), project, _db(project, args.db), out, force=args.force)
    except (FileNotFoundError, FileExistsError) as e:
        return _err(str(e))
    except ValueError as e:
        return _err(str(e), 1)
    print(json.dumps({"rebuilt": str(out)}))
    return 0


def _report(rep, project: Path, json_path: Path | None) -> int:
    if json_path:
        json_path.write_text(json.dumps(rep.to_json(), indent=2) + "\n")
    failed = [t.name for t in rep.tables if not t.ok] + [q.name for q in rep.queries if not q.ok]
    for t in rep.tables:
        if not t.ok:
            print(f"refdata: {t.name}: source {t.rows_source} rows, rebuilt {t.rows_rebuilt}; "
                  f"missing {t.missing[:2]}, extra {t.extra[:2]}", file=sys.stderr)
    for q in rep.queries:
        if not q.ok:
            print(f"refdata: query {q.name}: {q.detail}", file=sys.stderr)
    print(json.dumps({"project": project.name, "tables": len(rep.tables),
                      "rows": sum(t.rows_source for t in rep.tables),
                      "queries": len(rep.queries), "failed": failed}))
    return 0 if rep.ok else 1


def _compare(args) -> int:
    from refdata.compare import compare
    project = Path(args.project)
    for p in (args.src, args.rebuilt):
        if not Path(p).exists():
            return _err(f"{p} not found")
    rep = compare(Path(args.src), Path(args.rebuilt), project)
    return _report(rep, project, Path(args.json) if args.json else None)


def _roundtrip(args) -> int:
    import shutil

    from neorisk_simkit.io import read
    from neorisk_simkit.io.log import LogError, write_log
    from refdata.compare import compare
    from refdata.ingest import IngestError, ingest, owners
    from refdata.rebuild import rebuild
    project = Path(args.project)
    ref = Path(args.out_dir) if args.out_dir else REF
    db = _db(project, args.db)
    ds, log = ref / project.name, ref / f"{project.name}.log"
    out = ref / f"{project.name}.rebuilt.sqlite"
    try:
        ingest(project, db, ds, force=args.force)
        if log.exists():
            if not args.force:
                raise FileExistsError(f"{log} exists; pass --force to overwrite")
            shutil.rmtree(log)
        write_log(read(ds), log, owners=owners(project))
        rebuild(log, project, db, out, force=args.force)
    except (FileNotFoundError, FileExistsError) as e:
        return _err(str(e))
    except (IngestError, LogError, ValueError) as e:
        return _err(str(e), 1)
    return _report(compare(db, out, project), project, ref / f"{project.name}.compare.json")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"fetch": _fetch, "ingest": _ingest, "rebuild": _rebuild, "compare": _compare,
            "roundtrip": _roundtrip}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
