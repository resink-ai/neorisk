import argparse
import json
from collections.abc import Sequence

from bench.models import MODEL_ORDER
from bench.runner import run


def _model_list(value: str) -> tuple[str, ...]:
    names = tuple(n.strip() for n in value.split(",") if n.strip())
    bad = [n for n in names if n not in MODEL_ORDER]
    if bad or not names:
        raise argparse.ArgumentTypeError(
            f"unknown model(s) {bad or [value]}; choose from {','.join(MODEL_ORDER)}"
        )
    return names


def _run(args) -> int:
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


def _compare(args) -> int:
    from bench.compare import run_compare, write_outputs

    results = run_compare(
        args.data_dir,
        models=args.models,
        shap_rows=args.shap_rows,
        ann_shap_rows=args.ann_shap_rows,
        seed=args.seed,
        verbose=True,
    )
    write_outputs(results, args.out, args.json_path, lang=args.lang)
    print(f"{'model':<12}{'auc':>8}{'pr_auc':>8}{'ks':>8}{'rec@p0.5':>10}{'train s':>9}")
    for key, m in results["models"].items():
        if m["failed"] or not m["metrics"]:
            print(f"{key:<12}  FAILED: {m['failed']}")
            continue
        mt = m["metrics"]
        print(
            f"{key:<12}{mt['auc']:>8.4f}{mt['pr_auc']:>8.4f}{mt['ks']:>8.4f}"
            f"{mt['recall_at_p50']:>10.4f}{m['train_seconds']:>9.1f}"
        )
    print(f"report: {args.out}" + (f"  json: {args.json_path}" if args.json_path else ""))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="train baselines on a generated dataset")
    r.add_argument("data_dir")
    r.add_argument("--oracle", action="store_true", help="also train on golden features")
    r.add_argument("--json", dest="json_path", default=None)

    c = sub.add_parser("compare", help="compare five models and write an HTML report")
    c.add_argument("data_dir")
    c.add_argument("--out", required=True, help="HTML report path")
    c.add_argument("--json", dest="json_path", default=None, help="also write metrics JSON")
    c.add_argument(
        "--models",
        type=_model_list,
        default=MODEL_ORDER,
        help=f"comma list from {','.join(MODEL_ORDER)} (default: all)",
    )
    c.add_argument("--shap-rows", type=int, default=5000, help="test rows explained by SHAP")
    c.add_argument(
        "--ann-shap-rows", type=int, default=1000, help="rows explained by KernelSHAP for ANNs"
    )
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--lang", choices=("zh", "en"), default="zh")

    args = parser.parse_args(argv)
    return _compare(args) if args.cmd == "compare" else _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
