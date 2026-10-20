"""datagen replay RUN_DIR [--first N | --last N] [--from T] [--to T] [--types a,b]
                     [--where "amount>10000 and region=CA"] [--owners 0.01 | --owner-ids F]
                     [--resume-from KEY | --resume] [--sink URI]... [--pace asap|realtime|xN]
                     [--rate N] [--rebase now] [--with-labels] [--numbers] [--dry-run]

Streams a finished dataset's events, in canonical order, to one or more sinks (default:
stdout as JSON lines). It never reruns the simulation. The exit report goes to stderr; the
exit code is 1 if any sink failed.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def add_parser(sub) -> None:
    r = sub.add_parser("replay", help="stream a dataset's events to stdout, files or Kafka")
    r.add_argument("run_dir")
    r.add_argument("--first", type=int)
    r.add_argument("--last", type=int)
    r.add_argument("--from", dest="start", default=None, help="ISO time, inclusive")
    r.add_argument("--to", dest="end", default=None, help="ISO time, exclusive")
    r.add_argument("--types", default=None, help="comma list of event types")
    r.add_argument("--where", default=None)
    r.add_argument("--owners", type=float, default=None, help="share of owners, e.g. 0.01")
    r.add_argument("--owner-ids", default=None, help="file with one partition id per line")
    r.add_argument("--resume-from", default=None, metavar="KEY")
    r.add_argument("--resume", action="store_true", help="continue after the sinks' state")
    r.add_argument("--sink", action="append", default=[], metavar="URI")
    r.add_argument("--pace", default="asap")
    r.add_argument("--rate", type=float, default=None, help="max events per second")
    r.add_argument("--rebase", choices=["now"], default=None)
    r.add_argument("--with-labels", action="store_true")
    r.add_argument("--numbers", action="store_true", help="ids and amounts as JSON numbers")
    r.add_argument("--dry-run", action="store_true")


def _time(s: str | None) -> datetime | None:
    if s is None:
        return None
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def run(args) -> int:
    from datagen.cli import _err
    from neorisk_simkit.io import read
    from neorisk_simkit.replay import Pacing, Selection, dry_run, replay
    from neorisk_simkit.replay import sinks as S

    if args.first is not None and args.last is not None:
        return _err("replay: --first and --last are exclusive")
    try:
        sinks = [S.parse(u) for u in (args.sink or ["stdout"])]
    except ValueError as e:
        return _err(str(e))
    resume = args.resume_from
    if args.resume:
        keys = [S.read_state(t) for t in map(S.target_of, sinks) if t]
        keys = [k for k in keys if k]
        if keys:
            resume = min(keys, key=lambda k: tuple(int(x) for x in k.split(":")))
    ids = None
    if args.owner_ids:
        ids = [int(x) for x in Path(args.owner_ids).read_text().split()]
    sel = Selection(args.first, args.last, _time(args.start), _time(args.end),
                    args.types.split(",") if args.types else None, args.where, args.owners,
                    ids, resume, args.with_labels)
    pacing = Pacing(args.pace, args.rate, args.rebase == "now")
    run_ = read(args.run_dir)
    try:
        if args.dry_run:
            print(json.dumps(dry_run(run_, sel, pacing), indent=2))
            return 0
        rep = replay(run_, sel, sinks, pacing, args.numbers)
    except ValueError as e:
        return _err(f"replay: {e}")
    except RuntimeError as e:                        # a sink that cannot open (kafka extra)
        return _err(f"replay: {e}", 1)
    print(json.dumps(rep, default=str), file=sys.stderr)
    return 0 if rep["ok"] else 1
