"""refdata: real tables as simkit event logs, rebuilt and compared exactly.

    refdata fetch [--dest DIR] [--force]

Exit codes: 0 success, 1 a round trip or comparison differs, 2 usage error, missing source or
refusal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def _err(msg: str, code: int = 2) -> int:
    print(f"refdata: {msg}", file=sys.stderr)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refdata")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download the Spider2-lite SQLite databases")
    f.add_argument("--dest", default=None, help="default: data/spider2")
    f.add_argument("--force", action="store_true", help="download even if the files exist")
    return parser


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
    return {"fetch": _fetch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
