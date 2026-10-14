import argparse
from collections.abc import Sequence

from datagen.config import FraudConfig
from datagen.scenarios import SCENARIOS
from neorisk_simkit import export


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datagen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="generate a synthetic dataset")
    gen.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    gen.add_argument("--n-events", type=int, default=FraudConfig.n_events)
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--span-days", type=int, default=FraudConfig.span_days)
    gen.add_argument("--bad-rate", type=float, default=FraudConfig.target_bad_rate)
    gen.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    cfg = FraudConfig(
        n_events=args.n_events,
        seed=args.seed,
        span_days=args.span_days,
        target_bad_rate=args.bad_rate,
    )
    ds = SCENARIOS[args.scenario](cfg)
    export(ds, args.out)
    print(
        f"wrote {ds.events.height} events to {args.out} (bad rate {ds.events['label'].mean():.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
