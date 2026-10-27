"""Step 2 of the plan: score, measure on held-out labels, and propose candidates with evidence.

evaluate  head fitted on the training labels; recall@k of the held-out high-trust labels
          among the sampled addresses (seeds + random background) not used in training
propose   head fitted on every risk label; the top k unlabeled addresses with the evidence a
          reviewer needs: nearest labeled addresses, flows to labeled ones, other label mentions
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ethmodel import features
from ethmodel.data import Sample, Split, counterparty_types, events
from ethmodel.head import blend, graph_scores, pu_scores, recall_at

MIN_KIND = 10   # a per-kind head needs at least this many positives


def representations(which: str, out: Path, sample: Sample, split: Split) -> dict[str, np.ndarray]:
    if which == "baseline":
        ev = events(sample, split.train)
        return features.matrix(features.table(ev, counterparty_types(sample)))
    p = out / "embeddings.parquet"
    if not p.exists():
        raise SystemExit(f"no embeddings at {p}; run `ethmodel pretrain` and `ethmodel embed`")
    df = pl.read_parquet(p)
    cols = [c for c in df.columns if c.startswith("e")]
    return dict(zip(df["address"].to_list(), df.select(cols).to_numpy()))


def _score(names: list[str], x: np.ndarray, pos: dict[str, float], sample: Sample,
           graph_weight: float, negative: set[str] = frozenset()) -> np.ndarray:
    positive = np.array([a in pos for a in names])
    weight = np.array([pos.get(a, 1.0) for a in names])
    neg = np.array([a in negative for a in names])
    head = pu_scores(x, positive, weight, neg)
    g = graph_scores(sample.transfers, set(pos))
    return blend(head, np.array([g.get(a, 0.0) for a in names]), graph_weight)


def evaluate(which: str, reps: dict[str, np.ndarray], sample: Sample, split: Split, *,
             k: int = 100, graph_weight: float = 0.3) -> dict:
    names = sorted(reps)
    x = np.stack([reps[a] for a in names])
    scores = dict(zip(names, _score(names, x, split.train, sample, graph_weight)))
    pool = [a for a in sample.sampled() if a in scores and a not in split.train]
    held = split.holdout & set(pool)
    s = np.array([scores[a] for a in pool])
    return {"features": which, "candidates": len(pool), "held_out": len(held),
            f"recall@{k}": round(recall_at(s, pool, held, k), 3),
            f"chance@{k}": round(min(k, len(pool)) / len(pool), 3) if pool else None,
            "graph_weight": graph_weight}


def propose(reps: dict[str, np.ndarray], sample: Sample, split: Split, *, k: int = 20,
            graph_weight: float = 0.3) -> pl.DataFrame:
    names = sorted(reps)
    x = np.stack([reps[a] for a in names])
    risk = sample.risk()
    pos = dict(risk.select("address", "trust").iter_rows())
    scores = _score(names, x, pos, sample, graph_weight)
    kind_of = split.kinds
    per_kind = {}
    for kind in sorted({k_ for ks in kind_of.values() for k_ in ks}):
        members = {a: t for a, t in pos.items() if kind in kind_of.get(a, [])}
        if len(members) >= MIN_KIND:
            positive = np.array([a in members for a in names])
            per_kind[kind] = pu_scores(x, positive, np.array([members.get(a, 1.0)
                                                                for a in names]))
    # known services (exchange, bridge, ...) are not proposed: a reviewer would only say no
    services = set(sample.labels.filter(~pl.col("is_risk"))["address"].to_list())
    free = [i for i, a in enumerate(names) if a not in pos and a not in services]
    top = sorted(free, key=lambda i: -scores[i])[:k]

    z = (x - x.mean(0)) / (x.std(0) + 1e-9)
    z /= np.linalg.norm(z, axis=1, keepdims=True) + 1e-9
    pos_idx = [i for i, a in enumerate(names) if a in pos]
    flows = _flows(sample, set(pos))
    mentions = sample.labels.group_by("address").agg(
        (pl.col("label_kind") + "/" + pl.col("source")).str.join(", ").alias("m"))
    mentions = dict(mentions.iter_rows())
    rows = []
    for rank, i in enumerate(top, 1):
        a = names[i]
        sims = z[pos_idx] @ z[i]
        near = [f"{names[pos_idx[j]]} ({'/'.join(kind_of[names[pos_idx[j]]])}, "
                f"{sims[j]:.2f})" for j in np.argsort(-sims)[:3]]
        guess = max(per_kind, key=lambda kd: per_kind[kd][i]) if per_kind else None
        rows.append({"rank": rank, "address": a, "score": round(float(scores[i]), 4),
                     "kind_guess": guess, "nearest_labeled": "; ".join(near),
                     "flows_with_labeled": flows.get(a, ""), "other_labels": mentions.get(a, "")})
    return pl.DataFrame(rows)


def _flows(sample: Sample, bad: set[str]) -> dict[str, str]:
    """address -> its two largest flows with risk-labeled addresses, as text."""
    tr = sample.transfers.filter(pl.col("from_address").is_in(list(bad))
                                 ^ pl.col("to_address").is_in(list(bad)))
    out: dict[str, list[tuple[float, str]]] = {}
    for r in tr.iter_rows(named=True):
        other_is_from = r["from_address"] in bad
        me = r["to_address"] if other_is_from else r["from_address"]
        other = r["from_address"] if other_is_from else r["to_address"]
        unit = r["asset_symbol"] or "token"
        text = f"{'from' if other_is_from else 'to'} {other} {r['amount']:.4g} {unit}"
        out.setdefault(me, []).append((r["usd_approx"] or r["amount"] or 0.0, text))
    return {a: "; ".join(t for _, t in sorted(v, reverse=True)[:2]) for a, v in out.items()}
