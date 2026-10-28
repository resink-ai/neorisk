"""One fold: fit the model (and the baselines) on training devices, evaluate on test devices.

Model selection uses validation devices only: the epoch kept is the one with the best mean of
track and enroll top-1 on them, and the open-set threshold of every scorer is tuned on them.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import polars as pl

from devicefp import evaluate as ev
from devicefp.features import Encoded, encode
from devicefp.model import Config, embed, out_dim, save, train
from devicefp.profiles import Profiles

SPOOFER_CAP = 50      # fingerprints per spoofer device kept for evaluation (one has 3,635)
BASELINES = ("hamming", "naive_bayes")


def rows_of(p: Profiles, split: dict[str, str], which: str) -> np.ndarray:
    dev = p.table["device"].to_list()
    return np.array([i for i, d in enumerate(dev) if split.get(d) == which], dtype=np.int64)


def spoofer_rows(p: Profiles) -> np.ndarray:
    t = p.table.with_row_index("row").filter(pl.col("group") == "spoofer")
    t = t.with_columns(pl.int_range(pl.len()).over("device").alias("k"))
    return t.filter(pl.col("k") < SPOOFER_CAP)["row"].cast(pl.Int64).to_numpy()


def _subset(enc: Encoded, rows: np.ndarray) -> Encoded:
    return Encoded([enc.rows[i] for i in rows], enc.fields)


def fit(p: Profiles, split: dict[str, str], cfg: Config, device, init: str = "naive_bayes",
        drift: str = "calibrated", log=print):
    """Train on the split's training devices. drift="calibrated" sets each field's swap rate to
    cfg.drift.swap times its real change rate (relative to the mean change rate)."""
    devices = p.table["device"].to_numpy()
    days = p.table["seen_at"].dt.epoch("s").to_numpy() / 86400.0
    enc = encode(p)
    tr, va = rows_of(p, split, "train"), rows_of(p, split, "val")
    nb = ev.NaiveBayes.fit(ev.codes(p), devices, tr)
    if drift == "calibrated":
        rate = nb.p_change / nb.p_change.mean() * cfg.drift.swap
        cfg = dataclasses.replace(cfg, drift=dataclasses.replace(
            cfg.drift, swap_by_field=tuple(np.clip(rate, 0, 0.9).tolist())))
    weights = None
    if init == "naive_bayes":
        weights = np.sqrt(np.clip(nb.match - nb.differ, 0, None))
        weights = weights / weights.mean() * 0.7

    def validate(model):
        z = np.zeros((len(p), out_dim(model)), np.float32)
        z[va] = embed(model, _subset(enc, va), device)
        dist = ev.euclidean(z)
        t = ev.track(dist, devices, va).filter(pl.col("returning"))
        e = ev.enroll(dist, devices, days, va)
        return float(((t["rank"] == 1).mean() + (e["rank"] == 1).mean()) / 2)

    model, history = train(_subset(enc, tr), devices[tr], cfg, device, validate, log=log,
                           init_weights=weights)
    return model, enc, history


def scorers(p: Profiles, split: dict[str, str], z: np.ndarray | None,
            names=("model", *BASELINES)) -> dict[str, ev.Dist]:
    devices = p.table["device"].to_numpy()
    c = ev.codes(p)
    out = {}
    for n in names:
        if n == "model":
            out[n] = ev.euclidean(z)
        elif n == "hamming":
            out[n] = ev.hamming(c)
        elif n == "naive_bayes":
            out[n] = ev.NaiveBayes.fit(c, devices, rows_of(p, split, "train")).scorer(c)
    return out


def evaluate(p: Profiles, split: dict[str, str], dists: dict[str, ev.Dist]) -> dict:
    devices = p.table["device"].to_numpy()
    days = p.table["seen_at"].dt.epoch("s").to_numpy() / 86400.0
    sets = {"test": rows_of(p, split, "test")}
    if (p.table["group"] == "spoofer").any():
        sets["spoofer"] = spoofer_rows(p)
    va = rows_of(p, split, "val")
    report: dict[str, dict] = {}
    for name, dist in dists.items():
        thr = ev.best_threshold(ev.track(dist, devices, va))
        report[name] = {s: {"track": ev.track_metrics(ev.track(dist, devices, rows), thr),
                            "enroll": ev.enroll_metrics(ev.enroll(dist, devices, days, rows)),
                            "verify": ev.verify(dist, devices, rows)}
                        for s, rows in sets.items()}
    sizes = {s: {"fingerprints": len(r), "devices": len(set(devices[r]))}
             for s, r in sets.items()}
    return {"sets": sizes, "scorers": report}


def run_fold(p: Profiles, split: dict[str, str], cfg: Config, device, out: Path,
             init: str = "naive_bayes", drift: str = "calibrated",
             baselines: bool = True) -> dict:
    model, enc, history = fit(p, split, cfg, device, init, drift, log=lambda s: None)
    z = embed(model, enc, device)
    out.mkdir(parents=True, exist_ok=True)
    save(model, enc.fields, out / "encoder.pt")
    (out / "split.json").write_text(json.dumps(split))
    (out / "history.json").write_text(json.dumps(history))
    w = {(enc.fields[k] if isinstance(k, int) else k): v
         for k, v in model.field_weights().items()}
    (out / "weights.json").write_text(json.dumps(w, indent=1))
    pl.DataFrame({"device": p.table["device"], "group": p.table["group"],
                  "embedding": z.tolist()}).write_parquet(out / "embeddings.parquet")
    names = ("model", *BASELINES) if baselines else ("model",)
    metrics = evaluate(p, split, scorers(p, split, z, names))
    metrics["best_epoch"] = int(np.argmax([h["val"] for h in history]) + 1)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    return metrics


HEADLINE = [("track", "top1"), ("track", "open_set_acc"), ("enroll", "top1"),
            ("enroll", "top1 >3 months"), ("verify", "roc_auc"), ("verify", "tar@far=0.001"),
            ("verify", "eer")]


def summarize(folds: list[dict]) -> pl.DataFrame:
    """Mean and std over folds of the headline metrics, one row per scorer and set."""
    rows = []
    for k, m in enumerate(folds):
        for sc, sets in m["scorers"].items():
            for s, d in sets.items():
                rows.append({"fold": k, "scorer": sc, "set": s,
                             **{f"{a}.{b}": d[a][b] for a, b in HEADLINE}})
    t = pl.DataFrame(rows)
    cols = [c for c in t.columns if "." in c]
    return t.group_by("scorer", "set", maintain_order=True).agg(
        *(pl.col(c).mean().alias(c) for c in cols),
        *(pl.col(c).std().alias(c + " sd") for c in cols))


def compare(root: Path, runs: list[str]) -> pl.DataFrame:
    """One row per run (and the two baselines): mean validation score used for selection,
    mean test / spoofer metrics over folds, and the paired per-fold difference with naive
    Bayes on test track and enroll top-1 (mean and sd)."""
    def folds(run: str, scorer: str) -> list[tuple[float, dict]]:
        out = []
        for f in sorted((root / run).glob("fold*/metrics.json")):
            h = f.parent / "history.json"
            val = max(x["val"] for x in json.loads(h.read_text())) if h.exists() else None
            out.append((val, json.loads(f.read_text())["scorers"][scorer]))
        return out

    nb = folds("baselines", "naive_bayes")
    rows = []
    entries = [("naive_bayes", "baselines", "naive_bayes"), ("hamming", "baselines", "hamming")]
    entries += [(r, r, "model") for r in runs]
    for name, run, scorer in entries:
        fs = folds(run, scorer)
        if not fs or len(fs) != len(nb):
            continue
        row: dict = {"run": name}
        vals = [v for v, _ in fs if v is not None]
        row["val"] = float(np.mean(vals)) if vals else None
        for s in ("test", "spoofer"):
            for a, b in HEADLINE:
                row[f"{s} {a}.{b}"] = float(np.mean([m[s][a][b] for _, m in fs]))
        for a in ("track", "enroll"):
            d = [m["test"][a]["top1"] - n["test"][a]["top1"] for (_, m), (_, n) in
                 zip(fs, nb, strict=True)]
            row[f"Δ{a} vs nb"] = f"{np.mean(d):+.3f} ± {np.std(d, ddof=1):.3f}"
        rows.append(row)
    return pl.DataFrame(rows)
