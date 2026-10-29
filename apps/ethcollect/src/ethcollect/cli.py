"""eth-collect: run one connector, all label connectors, the toy sample, or a status report."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from ethcollect import connectors
from ethcollect.context import Context, FetchError, default_window

COUNTS = ("labels", "transfers", "addresses", "nft_transfers", "funders", "balances")


def _shared(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", type=Path, default=Path("data/eth"), help="default data/eth")
    p.add_argument("--since", type=date.fromisoformat, help="window start (default: 1 year ago)")
    p.add_argument("--until", type=date.fromisoformat, help="window end (default: today)")
    p.add_argument("--window-days", type=int, default=365, help="window length if no --since")
    p.add_argument("--limit", type=int, help="process at most N items (for a quick check)")
    p.add_argument("--refresh", action="store_true", help="ignore the raw cache and refetch")
    p.add_argument("--rate", type=float, help="calls per second (default: the source's own)")


def make_context(source: str, args) -> Context:
    until = args.until or default_window()[1]
    since = args.since or (until - timedelta(days=args.window_days))
    rate = args.rate or getattr(connectors.load(source), "DEFAULT_RATE", 2.0)
    return Context(out=args.out, source=source, since=since, until=until,
                   refresh=args.refresh, rate=rate, rate_given=args.rate is not None)


def run_connector(source: str, args) -> bool:
    module = connectors.load(source)
    ctx = make_context(source, args)
    ctx.note("window", [ctx.since.isoformat(), ctx.until.isoformat()])
    print(f"[{source}] {module.SUMMARY}")
    t0 = time.monotonic()
    ok = True
    try:
        module.run(ctx, args)
    except (FetchError, OSError) as e:
        ok = False
        ctx.note("error", str(e))
        print(f"  error: {e}")
    ctx.note("ok", ok)
    ctx.note("seconds", round(time.monotonic() - t0, 1))
    record = ctx.save_record({k: v for k, v in vars(args).items() if k != "func"})
    counts = {k: ctx.record[k] for k in COUNTS if k in ctx.record}
    print(f"  {'ok' if ok else 'FAILED'} {counts} in {ctx.record['seconds']}s -> {record}")
    return ok


def _connector_cmd(args) -> int:
    return 0 if run_connector(args.source, args) else 1


def _labels_cmd(args) -> int:
    failed = [s for s in connectors.label_sources()
              if not run_connector(s, namespace_for(s, args))]
    if failed:
        print(f"failed: {', '.join(failed)}")
    return 1 if failed else 0


def namespace_for(source: str, base, **opts) -> argparse.Namespace:
    """Options for one connector: the shared ones copied from `base`, the connector's own
    defaults, then `opts` on top. Lets `labels` and `sample` drive connectors directly."""
    p = argparse.ArgumentParser()
    _shared(p)
    connectors.load(source).add_arguments(p)
    ns = p.parse_args([])
    for k in ("out", "since", "until", "window_days", "limit", "refresh"):  # not rate: each
        setattr(ns, k, getattr(base, k))  # source keeps its own default
    ns.source = source
    for k, v in opts.items():
        setattr(ns, k, v)
    return ns


def _sample_cmd(args) -> int:
    from ethcollect.sample import toy

    return toy(args, run_connector)


def _status_cmd(args) -> int:
    from ethcollect.status import report

    print(report(args.out))
    return 0


def _new_source_cmd(args) -> int:
    from ethcollect.scaffold import new_source

    for p in new_source(args.name, args.kind):
        print(f"created {p}")
    print("next: register it in connectors/__init__.py SOURCES, fill in connector.py and the "
          "reference, then run it with --limit 10")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eth-collect", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for source in connectors.SOURCES:
        module = connectors.load(source)
        p = sub.add_parser(source, help=module.SUMMARY, description=module.__doc__,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        _shared(p)
        module.add_arguments(p)
        p.set_defaults(func=_connector_cmd, source=source)

    p = sub.add_parser("labels", help="run every label connector")
    _shared(p)
    p.set_defaults(func=_labels_cmd)

    p = sub.add_parser("sample", help="build the toy sample: labels, seeds, background, history")
    _shared(p)
    p.add_argument("recipe", choices=["toy"])
    p.add_argument("--seeds", type=int, default=300, help="labeled seed addresses (default 300)")
    p.add_argument("--background", type=int, default=700, help="random addresses (default 700)")
    p.add_argument("--cap", type=int, default=5, help="latest transfers kept per address")
    p.add_argument("--history", choices=["auto", "aws-scan", "etherscan", "blockscout"],
                   default="auto",
                   help="auto = etherscan if ETHERSCAN_API_KEY is set, else aws-scan")
    p.add_argument("--days", type=int, default=30,
                   help="aws-scan: whole days read, spread over the window (default 30)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--skip-labels", action="store_true", help="reuse the labels already on disk")
    p.set_defaults(func=_sample_cmd)

    p = sub.add_parser("status", help="connectors, last runs, table counts and data checks")
    p.add_argument("--out", type=Path, default=Path("data/eth"))
    p.set_defaults(func=_status_cmd)

    p = sub.add_parser("new-source", help="scaffold a new connector folder and reference")
    p.add_argument("name", help="kebab-case source name, e.g. chainabuse")
    p.add_argument("--kind", choices=["label", "chain"], required=True)
    p.set_defaults(func=_new_source_cmd)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
