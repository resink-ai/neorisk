"""dataset: validation datasets, an ordered event log in and expected tables out.

    dataset list [--json]
    dataset build NAME [--db SRC] [--record]
    dataset verify NAME [--json FILE]
    dataset resolve NAME/VERSION[/PATH]
    dataset context NAME
    dataset run NAME --engine duckdb|spark|flink|flink-stream [--json FILE]

Exit codes: 0 success, 1 a difference (or a build that differs from its lock), 2 a usage
error, an unknown name, a missing source or input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def _err(msg: str, code: int = 2) -> int:
    print(f"dataset: {msg}", file=sys.stderr)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dataset")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="the catalogue, and which versions are built here")
    ls.add_argument("--json", action="store_true", help="print JSON")
    b = sub.add_parser("build", help="run the recipe; write the log, results and manifest")
    b.add_argument("name")
    b.add_argument("--db", default=None, help="spider2 source; default: data/spider2/...")
    b.add_argument("--record", action="store_true", help="write <version>.lock.json")
    v = sub.add_parser("verify", help="the reference build over the log vs the results")
    v.add_argument("name")
    v.add_argument("--json", default=None, help="write the full report here")
    r = sub.add_parser("resolve", help="where a data name lives under the data root")
    r.add_argument("name")
    c = sub.add_parser("context", help="CONTEXT.md's counted sections, from the built version")
    c.add_argument("name")
    from dataset.engines import ENGINES
    rn = sub.add_parser("run", help="one engine builds the results from the log; graded")
    rn.add_argument("name")
    rn.add_argument("--engine", required=True, choices=ENGINES)
    rn.add_argument("--json", default=None, help="write the full run report here")
    return parser


def _state(cfg) -> str:
    from dataset.manifest import lock_diff
    from dataset.names import resolve
    mf = resolve(f"{cfg.name}/{cfg.version}") / "manifest.json"
    if not mf.exists():
        return "no"
    lock = cfg.dir / f"{cfg.version}.lock.json"
    if not lock.exists():
        return "unrecorded"
    m = json.loads(mf.read_text())
    root = mf.parent
    if lock_diff(json.loads(lock.read_text()), m) or not all(
            (root / p).exists() for p in m["files"]):
        return "stale"
    return "yes"


def _list(args) -> int:
    from dataset.config import all_configs
    from dataset.engines import latest_runs
    rows = [{"name": c.name, "kind": c.kind, "version": c.version, "built": _state(c),
             "engines": [e for e, r in latest_runs(c).items() if r["ok"]]}
            for c in all_configs()]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['name']:<24} {r['kind']:<10} {r['version']:<4} {r['built']:<10} "
                  f"{','.join(r['engines']) or '-'}")
    return 0


def _load(name: str):
    from dataset.config import load
    return load(name)


def _build(args) -> int:
    from dataset.spider2 import BuildError, build_spider2
    try:
        cfg = _load(args.name)
    except (FileNotFoundError, ValueError) as e:
        return _err(str(e))
    if cfg.kind == "synthetic":
        from dataset.synthetic import build_synthetic
        try:
            m = build_synthetic(cfg, record=args.record)
        except BuildError as e:
            return _err(str(e), 1)
        print(json.dumps({"name": cfg.name, "version": cfg.version, "counts": m["counts"]}))
        return 0
    if args.db:
        db = Path(args.db)
    else:
        from refdata.fetch import DATA
        from refdata.source import load_source
        db = DATA / load_source(cfg.dir).file
    try:
        m = build_spider2(cfg, db, record=args.record)
    except FileNotFoundError as e:
        return _err(str(e))
    except BuildError as e:
        return _err(str(e), 1)
    print(json.dumps({"name": cfg.name, "version": cfg.version, "counts": m["counts"]}))
    return 0


def _verify(args) -> int:
    from dataset.spider2 import verify
    from dataset.synthetic import verify_synthetic
    try:
        cfg = _load(args.name)
        rep = verify_synthetic(cfg) if cfg.kind == "synthetic" else verify(cfg)
    except (FileNotFoundError, ValueError) as e:
        return _err(str(e))
    asked = "questions" if cfg.kind == "synthetic" else "queries"
    results = [rep["recipe"], *rep["tables"], *rep[asked]]
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"ok": rep["ok"], "recipe": rep["recipe"].to_json(),
             "tables": [t.to_json() for t in rep["tables"]],
             asked: [q.to_json() for q in rep[asked]]}, indent=2) + "\n")
    for r in results:
        if not r.ok:
            print(f"dataset: {r.name}: {r.detail}; expected {r.rows_expected} rows, got "
                  f"{r.rows_got}; missing {r.missing[:2]}, extra {r.extra[:2]}", file=sys.stderr)
    print(json.dumps({"name": cfg.name, "tables": len(rep["tables"]),
                      asked: len(rep[asked]),
                      "failed": [r.name for r in results if not r.ok]}))
    return 0 if rep["ok"] else 1


def _resolve(args) -> int:
    from dataset.names import BadName, resolve
    try:
        print(resolve(args.name))
    except BadName as e:
        return _err(str(e))
    return 0


def _context(args) -> int:
    from dataset.context import render
    from dataset.names import resolve
    try:
        cfg = _load(args.name)
    except (FileNotFoundError, ValueError) as e:
        return _err(str(e))
    root = resolve(f"{cfg.name}/{cfg.version}")
    if not (root / "manifest.json").exists():
        return _err(f"{cfg.name} {cfg.version} is not built; run: uv run dataset build {cfg.name}")
    print(render(cfg, root))
    return 0


def _run(args) -> int:
    from dataset import engines
    try:
        cfg = _load(args.name)
        rep = engines.run(cfg, args.engine)
    except (FileNotFoundError, ValueError, engines.EngineNotReady) as e:
        return _err(str(e))
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2) + "\n")
    failed = [t for t in rep["tables"] if not t["ok"]]
    for t in failed:
        print(f"dataset: {t['name']}: {t['detail']}; expected {t['rows_expected']} rows, got "
              f"{t['rows_got']}; missing {t['missing'][:2]}, extra {t['extra'][:2]}",
              file=sys.stderr)
    print(json.dumps({k: rep[k] for k in ("name", "engine", "run_id", "ok", "wall_s",
                                          "peak_rss_mb", "events_per_s")}
                     | {"failed": [t["name"] for t in failed]}))
    return 0 if rep["ok"] else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"list": _list, "build": _build, "verify": _verify,
            "resolve": _resolve, "context": _context, "run": _run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
