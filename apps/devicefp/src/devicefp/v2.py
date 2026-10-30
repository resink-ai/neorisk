"""Device embedding v2 on device_profiles.pqt.

Inputs are every non-ID column, encoded per field. Same-device labels come from deviceId on
mobile profiles and from a web proxy entity (osId, gpuRenderer, screen) on web profiles. The
tmx_fuzzy_device_id column is never an input and is used only for evaluation.

    uv run python -m devicefp.v2 prepare
    uv run python -m devicefp.v2 train --name first
"""

from __future__ import annotations

import argparse
import json
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import torch
import torch.nn.functional as F
from torch import nn

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data/devicefp/device_profiles.pqt"
RUNS = ROOT / "data/devicefp/runs/v2"

PLACEHOLDERS = {"", "unknown", "02:00:00:00:00:00", "00:00:00:00:00:00", "<unknown ssid>"}
# identifiers: used for labels or evaluation, never as input
ID_COLUMNS = {
    "tmx_fuzzy_device_id", "deviceId", "androidId", "keychainId", "appId", "appSessionId",
    "osId", "idfv", "persistentID", "checksum", "serialNumber", "bssid", "ssid",
}
# timestamps, network addresses and the page URL: per session, not per device
DROP_COLUMNS = {
    "create_time", "bootTime", "firstAppInstallTime", "lastAppUpdate", "installPath",
    "appStoreReceipt", "page", "privateIp", "ipv6", "ip_latitude", "ip_longitude",
    "ip_city_name", "ip_country_code", "ip_country_name", "ip_country_name_en",
}
CAT_CAP = 4096  # categorical values kept per field; the rest go to one OOV code
MIN_COUNT = 3
NUM_BINS = 32


def _clean(values: pl.Series) -> pl.Series:
    s = values.cast(pl.String).str.strip_chars()
    return s.map_elements(lambda v: None if v is None or v in PLACEHOLDERS else v, return_dtype=pl.String)


def _encode_strings(s: pl.Series) -> tuple[np.ndarray, int]:
    arr = s.to_numpy()
    null = np.array([v is None for v in arr])
    text = np.where(null, "", arr.astype(object)).astype(str)
    uniq, inv, counts = np.unique(text, return_inverse=True, return_counts=True)
    code_of = np.ones(len(uniq), dtype=np.int64)  # OOV
    code_of[uniq == ""] = 0
    real = np.flatnonzero((uniq != "") & (counts >= MIN_COUNT))
    real = real[np.argsort(-counts[real], kind="stable")][: CAT_CAP - 2]
    code_of[real] = np.arange(2, 2 + len(real))
    return code_of[inv], CAT_CAP


def _encode_numeric(s: pl.Series) -> tuple[np.ndarray, int]:
    x = s.cast(pl.Float64).to_numpy()
    ok = ~np.isnan(x)
    codes = np.zeros(len(x), dtype=np.int64)
    if ok.sum() == 0:
        return codes, 2
    edges = np.unique(np.nanquantile(x[ok], np.linspace(0, 1, NUM_BINS + 1)))
    inner = edges[1:-1]
    codes[ok] = np.searchsorted(inner, x[ok], side="right") + 2
    return codes, int(codes.max()) + 1


def prepare(out: Path = RUNS, data: Path = DATA) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    df = pl.read_parquet(data)
    n = df.height

    fields, sizes, cols = [], [], []
    for name in df.columns:
        if name in ID_COLUMNS or name in DROP_COLUMNS:
            continue
        s = df[name]
        if s.dtype == pl.Boolean:
            s = s.cast(pl.String)
        if s.dtype == pl.String:
            codes, size = _encode_strings(_clean(s))
        elif s.dtype.is_numeric():
            codes, size = _encode_numeric(s)
        else:
            continue
        if size <= 2 or np.unique(codes).size <= 1:
            continue  # constant or all-null fields carry no identity
        fields.append(name)
        sizes.append(size)
        cols.append(codes)
    tokens = np.stack(cols, axis=1)
    offsets = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    tokens = tokens + offsets[None, :]

    dev = _clean(df["deviceId"]).to_numpy()
    osid = _clean(df["osId"]).to_numpy()
    gr = _clean(df["gpuRenderer"]).to_numpy()
    scr = (
        df.select(pl.concat_str(
            pl.col("screenWidth").cast(pl.String), pl.col("screenHeight").cast(pl.String),
            pl.col("screenScale").cast(pl.String), separator="x", ignore_nulls=False,
        )).to_series().to_numpy()
    )
    is_web = df["platform"].is_in(["Web", "PC", "Mac"]).to_numpy()

    entity_key = np.full(n, None, dtype=object)
    group_key = np.full(n, None, dtype=object)
    for i in range(n):
        if dev[i] is not None:
            entity_key[i] = "d|" + dev[i]
            group_key[i] = dev[i]
        elif osid[i] is not None and gr[i] is not None:
            entity_key[i] = f"w|{osid[i]}|{gr[i]}|{scr[i]}"
            group_key[i] = osid[i]

    def codes_of(values: np.ndarray) -> np.ndarray:
        keyed = np.array([v is not None for v in values])
        out_codes = np.full(n, -1, dtype=np.int64)
        if keyed.any():
            _, inv = np.unique(values[keyed].astype(str), return_inverse=True)
            out_codes[keyed] = inv
        return out_codes

    entity = codes_of(entity_key)
    group = codes_of(group_key)
    group_hash = np.array([zlib.crc32(str(g).encode()) % 100 if g >= 0 else -1 for g in group])
    split = np.where(group < 0, -1, np.where(group_hash < 70, 0, np.where(group_hash < 85, 1, 2)))

    tmx = codes_of(_clean(df["tmx_fuzzy_device_id"]).to_numpy())
    gv = codes_of(_clean(df["gpuVendor"]).to_numpy())

    np.save(out / "tokens.npy", tokens.astype(np.int64))
    np.savez(
        out / "labels.npz",
        entity=entity, split=split, tmx=tmx, gv=gv, is_web=is_web,
        platform=df["platform"].to_numpy(),
    )
    meta = {
        "rows": n, "fields": fields, "field_sizes": [int(s) for s in sizes],
        "vocab": int(sum(sizes)), "entities": int(entity.max() + 1),
        "train_rows": int(((split == 0) & (entity >= 0)).sum()),
        "val_rows": int((split == 1).sum()), "test_rows": int((split == 2).sum()),
        "mobile_rows": int((~is_web).sum()), "web_rows": int(is_web.sum()),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


# ---------------------------------------------------------------- model


class FieldEncoder(nn.Module):
    """Each field value is an embedding; a small transformer mixes fields; a unit vector comes out."""

    def __init__(self, vocab: int, n_fields: int, d: int = 64, layers: int = 2, heads: int = 4,
                 out: int = 128, dropout: float = 0.1):
        super().__init__()
        self.values = nn.Embedding(vocab, d)
        self.field = nn.Parameter(torch.randn(n_fields, d) * 0.02)
        self.cls = nn.Parameter(torch.zeros(1, 1, d))
        layer = nn.TransformerEncoderLayer(
            d, heads, 4 * d, dropout=dropout, batch_first=True, norm_first=True
        )
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.head = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, out))

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        h = self.values(tokens) + self.field[None]
        h = torch.cat([self.cls.expand(tokens.shape[0], -1, -1), h], dim=1)
        h = self.encoder(h)[:, 0]
        return F.normalize(self.head(h), dim=-1)


# ---------------------------------------------------------------- losses and metrics


def supcon_loss(z: torch.Tensor, entity: torch.Tensor, gv: torch.Tensor, tau: float,
                lam: float) -> torch.Tensor:
    """Weighted supervised contrastive loss.

    Same-entity pairs are positives with weight 1. Pairs with the same gpuVendor but a different
    entity get weight `lam`, which nudges the space toward requirement 2 without merging devices.
    """
    eye = torch.eye(z.shape[0], dtype=torch.bool, device=z.device)
    logits = (z @ z.T / tau).masked_fill(eye, -1e9)
    logp = logits - torch.logsumexp(logits, dim=1, keepdim=True)
    same_e = (entity[:, None] == entity[None, :]) & ~eye
    same_g = (gv[:, None] == gv[None, :]) & (gv[:, None] >= 0) & ~same_e & ~eye
    w = same_e.float() + lam * same_g.float()
    denom = w.sum(dim=1)
    valid = denom > 0
    per_anchor = -(w * logp).sum(dim=1) / denom.clamp(min=1e-9)
    return per_anchor[valid].mean()


def average_precision(score: np.ndarray, y: np.ndarray) -> float:
    if y.sum() == 0:
        return float("nan")
    order = np.argsort(-score, kind="stable")
    y = y[order].astype(np.float64)
    tp = np.cumsum(y)
    precision = tp / np.arange(1, len(y) + 1)
    return float((precision * y).sum() / y.sum())


def roc_auc(score: np.ndarray, y: np.ndarray) -> float:
    pos = y.sum()
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    ranks = np.empty(len(score))
    ranks[np.argsort(score, kind="stable")] = np.arange(1, len(score) + 1)
    return float((ranks[y.astype(bool)].sum() - pos * (pos + 1) / 2) / (pos * neg))


@torch.no_grad()
def embed_rows(model: FieldEncoder, tokens: torch.Tensor, rows: np.ndarray, device: str,
               bs: int = 8192) -> torch.Tensor:
    model.eval()
    out = []
    for i in range(0, len(rows), bs):
        idx = torch.as_tensor(rows[i:i + bs])
        out.append(model(tokens[idx].to(device)))
    return torch.cat(out)


@torch.no_grad()
def knn_pairs(z: torch.Tensor, k: int = 10, chunk: int = 4096):
    """Top-k neighbours by cosine inside one split. Returns (query, neighbour, cosine) arrays."""
    qs, nbs, cs = [], [], []
    for i in range(0, z.shape[0], chunk):
        sim = z[i:i + chunk] @ z.T
        rng = torch.arange(i, min(i + chunk, z.shape[0]), device=z.device)
        sim[torch.arange(len(rng)), rng] = -2.0
        vals, idx = sim.topk(k, dim=1)
        qs.append(rng.repeat_interleave(k).cpu())
        nbs.append(idx.reshape(-1).cpu())
        cs.append(vals.reshape(-1).cpu())
    return torch.cat(qs).numpy(), torch.cat(nbs).numpy(), torch.cat(cs).numpy()


def requirement_two(z: torch.Tensor, gv: np.ndarray, pairs: int = 400_000, seed: int = 0) -> dict:
    """Cosine for random pairs with the same vs different gpuVendor."""
    rng = np.random.default_rng(seed)
    labelled = np.flatnonzero(gv >= 0)
    if len(labelled) < 2:
        return {}
    a = rng.choice(labelled, pairs)
    b = rng.choice(labelled, pairs)
    keep = a != b
    a, b = a[keep], b[keep]
    cos = (z[a] * z[b]).sum(dim=1).cpu().numpy()
    same = gv[a] == gv[b]
    return {
        "same_gpuVendor_pairs": int(same.sum()),
        "mean_cos_same": float(cos[same].mean()) if same.any() else float("nan"),
        "mean_cos_diff": float(cos[~same].mean()),
        "auc_same_vs_diff": roc_auc(cos, same.astype(np.int64)),
    }


def candidate_scores(z: torch.Tensor, rows: np.ndarray, tmx: np.ndarray, is_web: np.ndarray):
    """kNN candidate pairs with cosine score, label (tmx equality) and whether the query is web."""
    qs, nbs, cs = knn_pairs(z)
    q_rows, n_rows = rows[qs], rows[nbs]
    ok = (tmx[q_rows] >= 0) & (tmx[n_rows] >= 0)
    y = (tmx[q_rows] == tmx[n_rows])[ok].astype(np.int64)
    return cs[ok], y, is_web[q_rows][ok]


def pr_at(s: np.ndarray, y: np.ndarray, t: float) -> tuple[float, float, int]:
    pred = s >= t
    tp = int((pred & (y == 1)).sum())
    return tp / max(int(pred.sum()), 1), tp / max(int(y.sum()), 1), int(pred.sum())


def tmx_metrics(s: np.ndarray, y: np.ndarray, web: np.ndarray, thresholds: tuple[float, ...]) -> dict:
    """PR and ROC over kNN candidate pairs, truth = tmx_fuzzy_device_id equality."""
    out = {"pairs": len(y), "positive_rate": float(y.mean()) if len(y) else float("nan")}
    out["pr_auc"] = average_precision(s, y)
    out["roc_auc"] = roc_auc(s, y)
    for name, mask in (("mobile", ~web), ("web", web)):
        out[f"pr_auc_{name}"] = average_precision(s[mask], y[mask])
        out[f"roc_auc_{name}"] = roc_auc(s[mask], y[mask])
    out["at_threshold"] = {}
    for t in thresholds:
        p, r, n = pr_at(s, y, t)
        out["at_threshold"][f"{t:.3f}"] = {"precision": p, "recall": r, "predicted_same": n}
    return out


def best_f1_threshold(s: np.ndarray, y: np.ndarray) -> float:
    grid = np.linspace(0.80, 0.999, 200)
    scores = []
    for t in grid:
        p, r, _ = pr_at(s, y, t)
        scores.append(2 * p * r / (p + r) if p + r > 0 else 0.0)
    return float(grid[int(np.argmax(scores))])


# ---------------------------------------------------------------- training


@dataclass
class Batches:
    """Samples P entities x K profiles per batch, half of them drawn from one gpuVendor."""

    rows_by_entity: dict[int, np.ndarray]
    entities: np.ndarray
    gv_of: dict[int, int]
    by_gv: dict[int, np.ndarray]
    P: int
    K: int
    rng: np.random.Generator

    def sample(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        anchor = self.rng.choice(self.entities)
        gv = self.gv_of[anchor]
        pool = self.by_gv.get(gv, self.entities) if self.rng.random() < 0.5 else self.entities
        if len(pool) < self.P:
            pool = self.entities
        chosen = np.concatenate([[anchor], self.rng.choice(pool, self.P - 1, replace=len(pool) < self.P)])
        chosen = np.unique(chosen)
        while len(chosen) < self.P:
            chosen = np.unique(np.concatenate([chosen, self.rng.choice(self.entities, 1)]))
        chosen = chosen[: self.P]
        rows, ent, gvs = [], [], []
        for e in chosen:
            pool_rows = self.rows_by_entity[int(e)]
            rows.append(self.rng.choice(pool_rows, self.K, replace=len(pool_rows) < self.K))
            ent.append(np.full(self.K, e))
            gvs.append(np.full(self.K, self.gv_of[int(e)]))
        return np.concatenate(rows), np.concatenate(ent), np.concatenate(gvs)


def build_batches(entity: np.ndarray, gv: np.ndarray, split_mask: np.ndarray, P: int, K: int,
                  seed: int) -> Batches:
    rows = np.flatnonzero(split_mask & (entity >= 0))
    ents, inv, counts = np.unique(entity[rows], return_inverse=True, return_counts=True)
    order = np.argsort(inv, kind="stable")
    sorted_rows = rows[order]
    starts = np.concatenate([[0], np.cumsum(counts)])
    rows_by_entity, gv_of = {}, {}
    multi = []
    for j, e in enumerate(ents):
        r = sorted_rows[starts[j]:starts[j + 1]]
        rows_by_entity[int(e)] = r
        gv_of[int(e)] = int(gv[r[0]])
        if len(r) >= 2:
            multi.append(int(e))
    multi = np.array(multi)
    by_gv: dict[int, list] = {}
    for e in multi:
        by_gv.setdefault(gv_of[int(e)], []).append(e)
    by_gv = {g: np.array(v) for g, v in by_gv.items() if g >= 0 and len(v) >= P}
    return Batches(rows_by_entity, multi, gv_of, by_gv, P, K, np.random.default_rng(seed))


def train(name: str, data: Path = RUNS, steps: int = 6000, eval_every: int = 500,
          P: int = 64, K: int = 4, tau: float = 0.1, lam: float = 0.1, lr: float = 1e-3,
          seed: int = 0, device: str = "cuda") -> dict:
    torch.manual_seed(seed)
    meta = json.loads((data / "meta.json").read_text())
    tokens = torch.from_numpy(np.load(data / "tokens.npy"))
    lab = np.load(data / "labels.npz")
    entity, split, tmx, gv, is_web = lab["entity"], lab["split"], lab["tmx"], lab["gv"], lab["is_web"]

    batches = build_batches(entity, gv, split == 0, P, K, seed)
    val_rows = np.flatnonzero(split == 1)
    test_rows = np.flatnonzero(split == 2)

    model = FieldEncoder(meta["vocab"], len(meta["fields"])).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.05)

    log, best_pr, best_state, best_step = [], -1.0, None, None
    for step in range(1, steps + 1):
        model.train()
        rows, ent, gvs = batches.sample()
        z = model(tokens[rows].to(device))
        loss = supcon_loss(
            z, torch.as_tensor(ent, device=device), torch.as_tensor(gvs, device=device), tau, lam
        )
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if step % eval_every == 0 or step == steps:
            s, y, _web = candidate_scores(embed_rows(model, tokens, val_rows, device), val_rows, tmx, is_web)
            entry = {"step": step, "loss": float(loss), "val_pr_auc": average_precision(s, y),
                         "val_roc_auc": roc_auc(s, y)}
            log.append(entry)
            print(json.dumps(entry), flush=True)
            if entry["val_pr_auc"] > best_pr:
                best_pr, best_step = entry["val_pr_auc"], step
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    s_val, y_val, web_val = candidate_scores(embed_rows(model, tokens, val_rows, device), val_rows, tmx, is_web)
    threshold = best_f1_threshold(s_val, y_val)  # chosen on validation only

    z_test = embed_rows(model, tokens, test_rows, device)
    s_test, y_test, web_test = candidate_scores(z_test, test_rows, tmx, is_web)
    result = {
        "name": name, "best_step": best_step, "threshold_val": threshold,
        "config": {"P": P, "K": K, "tau": tau, "lam": lam, "lr": lr, "steps": steps, "seed": seed},
        "log": log,
        "val": tmx_metrics(s_val, y_val, web_val, (0.99, 0.95, threshold)),
        "test": tmx_metrics(s_test, y_test, web_test, (0.99, 0.95, threshold)),
        "requirement_two_test": requirement_two(z_test, gv[test_rows]),
    }
    out_dir = data / name
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, out_dir / "model.pt")
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, default=float))
    return result


def main() -> None:
    p = argparse.ArgumentParser(prog="devicefp.v2")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    t = sub.add_parser("train")
    t.add_argument("--name", default="first")
    t.add_argument("--steps", type=int, default=6000)
    t.add_argument("--P", type=int, default=64)
    t.add_argument("--K", type=int, default=4)
    t.add_argument("--tau", type=float, default=0.1)
    t.add_argument("--lam", type=float, default=0.1)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    if args.cmd == "prepare":
        print(json.dumps(prepare(), indent=2))
    else:
        r = train(args.name, steps=args.steps, P=args.P, K=args.K, tau=args.tau, lam=args.lam,
                  lr=args.lr, seed=args.seed)
        print(json.dumps({k: r[k] for k in ("best_step", "val", "test", "threshold_val")}, indent=2, default=float))


if __name__ == "__main__":
    main()
