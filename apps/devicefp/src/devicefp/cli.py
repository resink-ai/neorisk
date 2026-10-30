"""devicefp: prepare (or synth) -> cv, all under data/devicefp/.

  devicefp prepare                  FP-Stalker dump -> data/devicefp/fpstalker/
  devicefp synth                    synthetic modern devices -> data/devicefp/synth/
  devicefp cv --name base           k-fold train + evaluate -> data/devicefp/runs/<data>/<name>/
  devicefp baselines                the hamming and naive Bayes linkers on the same folds
  devicefp geometry --name base     distances in the embedding space of a finished run
  devicefp report [runs...]         markdown table of runs against the baselines
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from devicefp.profiles import Profiles

RAW = Path("data/devicefp/raw/fpstalker")
RUNS = Path("data/devicefp/runs")


def _device():
    import torch

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _prepare(args) -> int:
    from devicefp.ingest import ingest
    from devicefp.profiles import from_fpstalker

    raw = ingest(args.raw / "tableFingerprints.sql", args.data / "fingerprints.parquet")
    consistent = set(pl.read_csv(args.raw / "data/consistent_extension_ids.csv")["user_id"])
    p = from_fpstalker(raw, consistent)
    p.write(args.data)
    print(p.table.group_by("group").agg(pl.len().alias("fingerprints"),
                                        pl.col("device").n_unique().alias("devices")))
    return 0


def _synth(args) -> int:
    from devicefp.synth import generate, load_intoli

    p = generate(load_intoli(args.intoli), devices=args.devices, seed=args.seed)
    p.write(args.data)
    print(f"{len(p)} profiles of {p.table['device'].n_unique()} devices -> {args.data}")
    return 0


def _config(args):
    from devicefp.features import Drift
    from devicefp.model import Config

    drift = Drift(args.swap, args.mask, args.drop_item, args.add_items, args.spoof)
    if args.drift == "none":
        drift = Drift(0, 0, 0, 0, args.spoof)
    return Config(epochs=args.epochs, seed=args.seed, drift=drift, dim=args.dim,
                  code_dim=args.code_dim, semantic=not args.no_semantic,
                  temperature=args.temperature, lr=args.lr)


def _profiles(args) -> Profiles:
    p = Profiles.read(args.data)
    if getattr(args, "drop_fields", ""):
        drop = set(args.drop_fields.split(","))
        p = Profiles(p.table, tuple(f for f in p.fields if f.name not in drop))
    return p


def _folds(args) -> list[int]:
    return list(range(args.folds)) if args.only is None else [args.only]


def _cv(args) -> int:
    from devicefp.evaluate import split_devices
    from devicefp.experiment import run_fold, summarize

    p, cfg, dev = _profiles(args), _config(args), _device()
    out = RUNS / args.data.name / args.name
    folds = []
    for k in _folds(args):
        split = split_devices(p, fold=k, folds=args.folds, seed=args.seed)
        m = run_fold(p, split, cfg, dev, out / f"fold{k}", init=args.init, drift=args.drift,
                     baselines=False)
        folds.append(m)
        print(f"{args.name} fold {k}: test track top1 "
              f"{m['scorers']['model']['test']['track']['top1']:.3f} "
              f"(best epoch {m['best_epoch']})", flush=True)
    s = summarize(folds)
    s.write_csv(out / "summary.csv")
    (out / "args.json").write_text(json.dumps(vars(args), default=str, indent=1))
    with pl.Config(tbl_cols=-1, tbl_width_chars=250, float_precision=3):
        print(s)
    return 0


def _baselines(args) -> int:
    from devicefp.evaluate import split_devices
    from devicefp.experiment import BASELINES, evaluate, scorers, summarize

    p = _profiles(args)
    out = RUNS / args.data.name / "baselines"
    folds = []
    for k in _folds(args):
        split = split_devices(p, fold=k, folds=args.folds, seed=args.seed)
        m = evaluate(p, split, scorers(p, split, None, BASELINES))
        (out / f"fold{k}").mkdir(parents=True, exist_ok=True)
        (out / f"fold{k}" / "metrics.json").write_text(json.dumps(m, indent=1))
        folds.append(m)
        print(f"baselines fold {k} done", flush=True)
    s = summarize(folds)
    s.write_csv(out / "summary.csv")
    with pl.Config(tbl_cols=-1, tbl_width_chars=250, float_precision=3):
        print(s)
    return 0


def _geometry(args) -> int:
    import numpy as np

    from devicefp.experiment import rows_of
    from devicefp.geometry import geometry

    p = _profiles(args)
    out = RUNS / args.data.name / args.name
    res = []
    for k in _folds(args):
        f = out / f"fold{k}"
        z = np.array(pl.read_parquet(f / "embeddings.parquet")["embedding"].to_list(),
                     dtype=np.float32)
        split = json.loads((f / "split.json").read_text())
        res.append(geometry(p, z, rows_of(p, split, "test")))
        print(f"fold {k}: spearman {res[-1]['spearman_distance_vs_fields_differing']:.3f} "
              f"margin {res[-1]['margin_ok']:.3f}", flush=True)
    (out / "geometry.json").write_text(json.dumps(res, indent=1))
    return 0


def _report(args) -> int:
    from devicefp.experiment import compare

    root = RUNS / args.data.name
    runs = args.runs or sorted(d.name for d in root.iterdir()
                               if d.is_dir() and d.name != "baselines")
    t = compare(root, runs)
    cols = ["run", "val", "test track.top1", "test track.open_set_acc", "test enroll.top1",
            "test enroll.top1 >3 months", "test verify.tar@far=0.001", "test verify.eer",
            "spoofer track.top1", "spoofer enroll.top1", "Δtrack vs nb", "Δenroll vs nb"]
    t = t.select(cols)
    head = "| " + " | ".join(cols) + " |"
    print(head + "\n|" + "---|" * len(cols))
    for r in t.iter_rows():
        print("| " + " | ".join("" if v is None else f"{v:.3f}" if isinstance(v, float)
                                else str(v) for v in r) + " |")
    t.write_csv(root / "report.csv")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    from devicefp.features import Drift

    ap = argparse.ArgumentParser(prog="devicefp")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def shared(p, data="data/devicefp/fpstalker"):
        p.add_argument("--data", type=Path, default=Path(data),
                       help=f"profiles folder (default {data})")
        p.add_argument("--seed", type=int, default=7)

    p = sub.add_parser("report", help="markdown table of finished runs vs the baselines")
    shared(p)
    p.add_argument("runs", nargs="*", help="run names (default: all)")
    p.set_defaults(fn=_report)

    p = sub.add_parser("prepare", help="FP-Stalker dump -> profiles")
    shared(p)
    p.add_argument("--raw", type=Path, default=RAW)
    p.set_defaults(fn=_prepare)

    p = sub.add_parser("synth", help="synthetic modern devices from intoli user-agents")
    shared(p, "data/devicefp/synth")
    p.add_argument("--intoli", type=Path,
                   default=Path("data/devicefp/raw/intoli/package/dist/user-agents.json"))
    p.add_argument("--devices", type=int, default=3000)
    p.set_defaults(fn=_synth)

    for name, fn in (("cv", _cv), ("baselines", _baselines), ("geometry", _geometry)):
        p = sub.add_parser(name)
        shared(p)
        p.add_argument("--folds", type=int, default=5)
        p.add_argument("--only", type=int, default=None, help="run a single fold")
        p.add_argument("--drop-fields", default="",
                       help="comma-separated fields to leave out")
        if name != "baselines":
            p.add_argument("--name", required=True, help="run name under data/devicefp/runs/")
        if name == "cv":
            p.add_argument("--epochs", type=int, default=60)
            p.add_argument("--dim", type=int, default=64)
            p.add_argument("--code-dim", type=int, default=32,
                           help="identity channel size per field (0: semantic channel only)")
            p.add_argument("--no-semantic", action="store_true",
                           help="identity channel only")
            p.add_argument("--init", choices=["naive_bayes", "none"], default="naive_bayes",
                           help="identity-channel starting weights")
            p.add_argument("--drift", choices=["none", "calibrated", "uniform"],
                           default="none",
                           help="training augmentation: none (selected on validation), "
                                "per-field swap rates from real change rates, or one rate")
            d = Drift()
            for k in ("swap", "mask", "drop_item", "add_items", "spoof"):
                p.add_argument(f"--{k.replace('_', '-')}", type=float, default=getattr(d, k))
            p.add_argument("--temperature", type=float, default=0.07)
            p.add_argument("--lr", type=float, default=2e-3)
        p.set_defaults(fn=fn)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
