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


def _curves(args) -> int:
    import json as _json
    from pathlib import Path

    from bench.curves import render_curves, run_curves

    res = run_curves(args.data_dir, args.rare_dir, seed=args.seed, verbose=True)
    Path(args.out).write_text(render_curves(res, lang=args.lang), encoding="utf-8")
    if args.json_path:
        Path(args.json_path).write_text(_json.dumps(res), encoding="utf-8")
    print(f"report: {args.out}")
    return 0


def _temporal(args) -> int:
    import json as _json
    from pathlib import Path

    from bench.temporal import render_temporal, run_temporal
    from bench.temporal_sim import TemporalConfig, generate_temporal

    cfg = TemporalConfig(seed=args.seed)
    if args.data_out:
        Path(args.data_out).mkdir(parents=True, exist_ok=True)
        generate_temporal(cfg).write_parquet(Path(args.data_out) / "events.parquet")
    res = run_temporal(cfg)
    Path(args.out).write_text(render_temporal(res, lang=args.lang), encoding="utf-8")
    if args.json_path:
        Path(args.json_path).write_text(_json.dumps(res), encoding="utf-8")
    print(f"report: {args.out}")
    return 0


def _datagen(args) -> int:
    import json as _json

    from bench.datagen_loader import run_maturity

    res = run_maturity(args.run_dir, args.event, args.key, args.role or None,
                       args.cutoff_day, args.test_days, args.seed)
    print(_json.dumps(res, indent=2))
    return 0


def _method_list(value: str) -> list[str]:
    from bench.discover.methods import ORDER

    names = [n.strip() for n in value.split(",") if n.strip()]
    bad = [n for n in names if n not in ORDER]
    if bad or not names:
        raise argparse.ArgumentTypeError(
            f"unknown method(s) {bad or [value]}; choose from {','.join(ORDER)}")
    return names


def _ints(value: str) -> tuple[int, ...]:
    return tuple(int(x) for x in value.split(",") if x.strip())


def _discover(args) -> int:
    from pathlib import Path

    from bench.discover.bench import run_bench
    from bench.discover.report import write
    from bench.discover.world import load

    out = Path(args.out)
    run_dir = args.run
    if args.generate:
        try:
            from datagen.cli import main as datagen
        except ImportError:
            print("--generate needs the datagen package (uv sync --all-packages)")
            return 2
        run_dir = out / "run"
        cmd = ["run", args.generate, "--seed", str(args.seed), "--out", str(run_dir), "--force"]
        cmd += ["--profile", args.profile] if args.profile else []
        for o in args.overlay:
            cmd += ["--overlay", o]
        for kv in args.set:
            cmd += ["--set", kv]
        if datagen(cmd) != 0:
            return 1
    world, truth = load(run_dir, seed=args.seed)
    print(f"world: {len(world.user_ids):,} users, {int(truth.bad.sum())} bad "
          f"({int(truth.stealth.sum())} stealth)")
    res = run_bench(world, truth, methods=args.methods, k=args.k, rounds=args.rounds,
                    sweep=args.sweep, draws=args.seed_draws, n_seeds=args.n_seeds,
                    report_day=args.report_day, seed=args.seed, log=print)
    page = write(res, out, lang=args.lang)
    full = str(args.rounds)
    print(f"{'method':<13}{'found':>7}{'recall':>9}{'prec':>8}{'auc':>8}{'pr_auc':>8}"
          f"{'stealth':>9}")
    for k, m in sorted(res["methods"].items(),
                       key=lambda kv: -kv[1]["by_budget"][full]["recall"]["mean"]):
        a = m["by_budget"][full]
        found = a["found"]["mean"][-1] if isinstance(a["found"], dict) and a["found"]["mean"] \
            else 0
        print(f"{k:<13}{found:>7.0f}{a['recall']['mean']:>9.3f}{a['precision']['mean']:>8.3f}"
              f"{a['auc']['mean']:>8.3f}{a['pr_auc']['mean']:>8.3f}"
              f"{a['stealth_recall']['mean']:>9.3f}")
    print(f"report: {page}  json: {out / 'discover.json'}")
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

    k = sub.add_parser("curves", help="ROC/PR curve shapes: imbalance, stairs, leakage")
    k.add_argument("data_dir", help="base dataset (needs golden.parquet for the leak case)")
    k.add_argument("rare_dir", help="same scenario generated with a very low bad rate")
    k.add_argument("--out", required=True)
    k.add_argument("--json", dest="json_path", default=None)
    k.add_argument("--seed", type=int, default=0)
    k.add_argument("--lang", choices=("zh", "en"), default="zh")

    tp = sub.add_parser("temporal", help="label maturity and future-leakage experiments")
    tp.add_argument("--out", required=True)
    tp.add_argument("--json", dest="json_path", default=None)
    tp.add_argument("--data-out", default=None, help="also write the sample events.parquet here")
    tp.add_argument("--seed", type=int, default=7)
    tp.add_argument("--lang", choices=("zh", "en"), default="zh")

    dg = sub.add_parser("datagen", help="train on any datagen dataset with label maturity")
    dg.add_argument("run_dir", help="a datagen dataset (with labels/labels.parquet)")
    dg.add_argument("--event", required=True, help="the event table whose rows are scored")
    dg.add_argument("--key", required=True, help="the column the labels' target_id matches")
    dg.add_argument("--role", action="append", default=[], help="label roles (repeatable)")
    dg.add_argument("--cutoff-day", type=float, default=60.0)
    dg.add_argument("--test-days", type=float, default=14.0)
    dg.add_argument("--seed", type=int, default=0)

    ds = sub.add_parser("discover", help="label discovery: grow hidden ring labels from seeds")
    src = ds.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="an existing datagen run with ring labels")
    src.add_argument("--generate", metavar="PROJECT", help="simulate the run first, into OUT/run")
    ds.add_argument("--profile", default=None)
    ds.add_argument("--overlay", action="append", default=[])
    ds.add_argument("--set", action="append", default=[], metavar="K=V")
    ds.add_argument("--seed", type=int, default=42, help="simulation, id and method seed")
    ds.add_argument("--methods", type=_method_list, default=None, help="comma-separated keys")
    ds.add_argument("--k", type=int, default=50, help="reviews per round")
    ds.add_argument("--rounds", type=int, default=10)
    ds.add_argument("--sweep", type=_ints, default=(0, 2, 5, 10), help="budgets in rounds")
    ds.add_argument("--seed-draws", type=int, default=5)
    ds.add_argument("--n-seeds", type=int, default=5)
    ds.add_argument("--report-day", type=float, default=45.0,
                    help="seeds are bad users whose label is known by this day")
    ds.add_argument("--out", required=True)
    ds.add_argument("--lang", choices=("zh", "en"), default="zh")

    args = parser.parse_args(argv)
    if args.cmd == "discover":
        if args.methods is None:
            from bench.discover.methods import ORDER
            args.methods = list(ORDER)
        return _discover(args)
    if args.cmd == "datagen":
        return _datagen(args)
    if args.cmd == "temporal":
        return _temporal(args)
    if args.cmd == "curves":
        return _curves(args)
    return _compare(args) if args.cmd == "compare" else _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
