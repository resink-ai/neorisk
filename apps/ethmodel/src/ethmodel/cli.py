"""ethmodel: pretrain -> embed -> expand (and bench), all reading an eth-collect sample."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from ethmodel.data import Sample, counterparty_types, events, split_labels


def _shared(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sample", type=Path, default=Path("data/eth/samples/toy"),
                   help="an eth-collect sample folder (default data/eth/samples/toy)")
    p.add_argument("--out", type=Path, default=Path("data/eth/model/toy"),
                   help="checkpoint, embeddings and reports (default data/eth/model/toy)")
    p.add_argument("--holdout", type=float, default=0.3,
                   help="share of high-trust labels hidden for evaluation (default 0.3)")
    p.add_argument("--seed", type=int, default=7)


def _load(args):
    sample = Sample.read(args.sample)
    return sample, split_labels(sample, holdout=args.holdout, seed=args.seed)


def _sequences(sample, split):
    from ethmodel.tokens import encode

    return encode(events(sample, split.train), counterparty_types(sample))


def _pretrain(args) -> int:
    from ethmodel.model import pretrain

    sample, split = _load(args)
    seqs = _sequences(sample, split)
    print(f"[pretrain] {len(seqs)} sequences, {sum(len(s) - 1 for s in seqs.values())} events; "
          f"{len(split.train)} training labels, {len(split.holdout)} held out")
    summary = pretrain(seqs, args.out, epochs=args.epochs, batch=args.batch, lr=args.lr,
                       seed=args.seed)
    first, last = summary["history"][0], summary["history"][-1]
    print(f"[pretrain] {summary['parameters']:,} parameters, {summary['seconds']}s; masked "
          f"{first['masked']:.3f} -> {last['masked']:.3f}, contrast {first['contrast']:.3f} -> "
          f"{last['contrast']:.3f}; saved {args.out / 'encoder.pt'}")
    return 0


def _embed(args) -> int:
    from ethmodel.model import embed, load

    sample, split = _load(args)
    seqs = _sequences(sample, split)
    vecs = embed(load(args.out), seqs)
    names = sorted(vecs)
    width = len(next(iter(vecs.values())))
    df = pl.DataFrame({"address": names, "n_events": [len(seqs[a]) - 1 for a in names],
                       **{f"e{j}": [float(vecs[a][j]) for a in names] for j in range(width)}})
    df.write_parquet(args.out / "embeddings.parquet")
    print(f"[embed] {df.height} addresses x {width} -> {args.out / 'embeddings.parquet'}")
    return 0


def _expand(args) -> int:
    from ethmodel.expand import evaluate, propose, representations

    sample, split = _load(args)
    which = ["embed", "baseline"] if args.features == "both" else [args.features]
    results = []
    for w in which:
        reps = representations(w, args.out, sample, split)
        results.append(evaluate(w, reps, sample, split, k=args.eval_k,
                                graph_weight=args.graph_weight))
        print(json.dumps(results[-1]))
        if w == which[0]:
            cand = propose(reps, sample, split, k=args.k, graph_weight=args.graph_weight)
            args.out.mkdir(parents=True, exist_ok=True)
            cand.write_csv(args.out / "candidates.csv")
            print(f"[expand] top {cand.height} candidates from {w} -> "
                  f"{args.out / 'candidates.csv'}")
    (args.out / "evaluation.json").write_text(json.dumps(results, indent=2))
    return 0


def _bench(args) -> int:
    from ethmodel.adapter import run
    from ethmodel.expand import representations

    sample, split = _load(args)
    reps = {w: representations(w, args.out, sample, split) for w in ("embed", "baseline")}
    table = run(reps, sample, split, rounds=args.rounds, k=args.k, seed=args.seed)
    with pl.Config(tbl_rows=50):
        print(table.pivot(on="method", index="round", values="held_out_found"))
    table.write_csv(args.out / "bench.csv")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ethmodel", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pretrain", help="masked event modeling + same-address contrast")
    _shared(p)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.set_defaults(func=_pretrain)

    p = sub.add_parser("embed", help="[CLS] embedding per address -> embeddings.parquet")
    _shared(p)
    p.set_defaults(func=_embed)

    p = sub.add_parser("expand", help="recall on held-out labels + candidates with evidence")
    _shared(p)
    p.add_argument("--features", choices=["both", "embed", "baseline"], default="both")
    p.add_argument("--k", type=int, default=20, help="candidates to propose (default 20)")
    p.add_argument("--eval-k", type=int, default=100, help="recall@k (default 100)")
    p.add_argument("--graph-weight", type=float, default=0.3)
    p.set_defaults(func=_expand)

    p = sub.add_parser("bench", help="review rounds on bench discover's loop, held-out labels "
                                     "as the reviewer")
    _shared(p)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--k", type=int, default=20)
    p.set_defaults(func=_bench)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
