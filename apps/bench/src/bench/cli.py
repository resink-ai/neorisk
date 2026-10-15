import argparse
import json
from collections.abc import Sequence

from bench.runner import run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="train baselines on a generated dataset")
    r.add_argument("data_dir")
    r.add_argument("--oracle", action="store_true", help="also train on golden features")
    r.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)

    rows = run(args.data_dir, oracle=args.oracle)
    print(f"{'model':<14}{'split':<7}{'auc':>8}{'pr_auc':>8}{'rec@p0.5':>10}")
    for x in rows:
        print(
            f"{x['model']:<14}{x['split']:<7}{x['auc']:>8.3f}{x['pr_auc']:>8.3f}"
            f"{x['recall_at_precision']:>10.3f}"
        )
    if args.json_path:
        with open(args.json_path, "w") as f:
            json.dump(rows, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
