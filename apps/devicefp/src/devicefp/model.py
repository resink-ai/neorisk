"""The encoder and its training.

A profile is a bag of hashed tokens grouped by field; each field's tokens are averaged into one
vector, so a 300-font list and a one-value field weigh the same. The output is L2-normalised:
on the unit sphere euclidean distance is a monotone function of cosine, d^2 = 2 - 2 cos.
See `Encoder` for its two channels.

Training is supervised contrastive (SupCon): a batch holds P devices with two views each.
A device seen several times gives two different real fingerprints, each lightly drifted; a
device seen once gives two drifted copies of its only fingerprint. Every other device in the
batch is a negative.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from devicefp.features import BUCKETS, MASK, Drift, Encoded, augment


@dataclass
class Config:
    width: int = 64
    dim: int = 64
    layers: int = 2
    heads: int = 4
    dropout: float = 0.1
    temperature: float = 0.07
    devices_per_batch: int = 128
    epochs: int = 60
    lr: float = 2e-3
    weight_decay: float = 1e-4
    seed: int = 7
    drift: Drift = field(default_factory=Drift)
    field_dropout: float = 0.0     # ablation knob: drop whole fields at train time only
    semantic: bool = True          # the learned channel
    code_dim: int = 32             # the identity channel, per field (0 = off)


class Encoder(nn.Module):
    """Two channels, concatenated and L2-normalised:

    semantic  trained token vectors -> per-field mean -> transformer -> `dim` numbers. Learns
              that Firefox/41 and Firefox/42, or two font lists one font apart, are close.
    identity  per field, a frozen random unit vector per value (the mean of item vectors for a
              set, re-normalised), times a learned field weight w_f. Two profiles then have
              squared distance sum_f w_f^2 * |r(a_f) - r(b_f)|^2, about 2 * sum of w_f^2 over
              the fields that differ: a weighted mismatch count, which can express the naive
              Bayes linker exactly and works for values never seen in training.
    """

    def __init__(self, n_fields: int, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.n_fields = n_fields
        if cfg.semantic:
            self.tokens = nn.Embedding(BUCKETS, cfg.width)
            self.field = nn.Embedding(n_fields, cfg.width)
            layer = nn.TransformerEncoderLayer(cfg.width, cfg.heads, 4 * cfg.width,
                                               cfg.dropout, batch_first=True, norm_first=True)
            self.body = nn.TransformerEncoder(layer, cfg.layers, enable_nested_tensor=False)
            self.norm = nn.LayerNorm(cfg.width)
            self.out = nn.Sequential(nn.Linear(cfg.width, cfg.width), nn.GELU(),
                                     nn.Linear(cfg.width, cfg.dim))
            nn.init.normal_(self.tokens.weight, std=0.5)
            self.w_sem = nn.Parameter(torch.zeros(()))
        if cfg.code_dim:
            g = torch.Generator().manual_seed(12345)     # fixed: codes must not depend on seed
            codes = F.normalize(torch.randn(BUCKETS, cfg.code_dim, generator=g), dim=-1)
            codes[MASK] = 0                              # a hidden field gives no evidence
            self.register_buffer("codes", codes, persistent=False)
            self.w_field = nn.Parameter(torch.zeros(n_fields))

    def _pool(self, e: torch.Tensor, seg: torch.Tensor, n: int) -> torch.Tensor:
        d = e.shape[1]
        pooled = torch.zeros(n * self.n_fields, d, device=e.device).index_add_(0, seg, e)
        count = torch.zeros(n * self.n_fields, device=e.device).index_add_(
            0, seg, torch.ones_like(seg, dtype=torch.float))
        return (pooled / count.clamp(min=1).unsqueeze(1)).view(n, self.n_fields, d)

    def forward(self, tok: torch.Tensor, seg: torch.Tensor, n: int) -> torch.Tensor:
        """tok, seg [tokens]: bucket id and row*n_fields+field of every token -> [n, out]."""
        parts = []
        if self.cfg.semantic:
            h = self._pool(self.tokens(tok), seg, n) + self.field.weight
            h = self.norm(self.body(h)).mean(1)
            parts.append(F.normalize(self.out(h), dim=-1) * F.softplus(self.w_sem))
        if self.cfg.code_dim:
            c = F.normalize(self._pool(self.codes[tok], seg, n), dim=-1)
            parts.append((c * F.softplus(self.w_field)[:, None]).flatten(1))
        return F.normalize(torch.cat(parts, 1), dim=-1)

    def field_weights(self) -> dict[str, float]:
        out = {}
        if self.cfg.code_dim:
            out.update(enumerate(F.softplus(self.w_field).tolist()))
        if self.cfg.semantic:
            out["semantic"] = float(F.softplus(self.w_sem))
        return out


def collate(rows: list[list[np.ndarray]], device: torch.device):
    nf = len(rows[0])
    toks, segs = [], []
    for i, row in enumerate(rows):
        for f, t in enumerate(row):
            toks.append(t)
            segs.append(np.full(len(t), i * nf + f, dtype=np.int64))
    return (torch.from_numpy(np.concatenate(toks)).to(device),
            torch.from_numpy(np.concatenate(segs)).to(device), len(rows))


@torch.no_grad()
def embed(model: Encoder, enc: Encoded, device: torch.device, batch: int = 1024) -> np.ndarray:
    model.eval()
    out = [model(*collate(enc.rows[i:i + batch], device)).cpu().numpy()
           for i in range(0, len(enc), batch)]
    return np.concatenate(out) if out else np.zeros((0, out_dim(model)), np.float32)


def out_dim(model: Encoder) -> int:
    c = model.cfg
    return (c.dim if c.semantic else 0) + model.n_fields * c.code_dim


def supcon(z: torch.Tensor, labels: torch.Tensor, t: float) -> torch.Tensor:
    sim = z @ z.T / t
    eye = torch.eye(len(z), dtype=torch.bool, device=z.device)
    sim = sim.masked_fill(eye, -1e9)
    pos = (labels[:, None] == labels[None, :]) & ~eye
    logp = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    return -(logp * pos).sum(1).div(pos.sum(1).clamp(min=1)).mean()


def _views(groups: list[np.ndarray], enc: Encoded, rng: np.random.Generator, d: Drift,
           field_dropout: float):
    rows = []
    for g in groups:
        a, b = (rng.choice(g, 2, replace=False) if len(g) > 1 else (g[0], g[0]))
        for i in (a, b):
            r = augment(enc.rows[i], enc, rng, d)
            if field_dropout:
                r = [np.array([0]) if rng.random() < field_dropout else t for t in r]
            rows.append(r)
    return rows


def train(enc: Encoded, devices: np.ndarray, cfg: Config, device: torch.device,
          validate=None, log=print,
          init_weights: np.ndarray | None = None) -> tuple[Encoder, list[dict]]:
    """enc: encoded training profiles; devices[i]: device label of profile i.
    validate(model) -> float (higher is better) picks the best epoch when given.
    init_weights [fields]: starting identity-channel weights (the naive Bayes mismatch cost
    sqrt(match - differ) reproduces that linker at step 0)."""
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    _, inv = np.unique(devices, return_inverse=True)
    groups = [np.flatnonzero(inv == k) for k in range(inv.max() + 1)]
    model = Encoder(len(enc.fields), cfg).to(device)
    if init_weights is not None and cfg.code_dim:
        with torch.no_grad():
            w = torch.as_tensor(init_weights, dtype=torch.float).clamp(min=1e-3)
            model.w_field.copy_(torch.log(torch.expm1(w)))           # softplus^-1
            if cfg.semantic:
                model.w_sem.copy_(torch.log(torch.expm1(w.mean())))
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    steps = cfg.epochs * max(1, len(groups) // cfg.devices_per_batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, cfg.lr, total_steps=steps, pct_start=0.1)
    history, best, best_state = [], -1.0, None
    t0 = time.time()
    for epoch in range(cfg.epochs):
        model.train()
        order = rng.permutation(len(groups))
        losses = []
        for s in range(0, len(order) - cfg.devices_per_batch + 1, cfg.devices_per_batch):
            batch = [groups[k] for k in order[s:s + cfg.devices_per_batch]]
            z = model(*collate(_views(batch, enc, rng, cfg.drift, cfg.field_dropout), device))
            labels = torch.arange(len(batch), device=device).repeat_interleave(2)
            loss = supcon(z, labels, cfg.temperature)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            losses.append(loss.item())
        rec = {"epoch": epoch + 1, "loss": float(np.mean(losses)), "sec": time.time() - t0}
        if validate is not None:
            rec["val"] = validate(model)
            if rec["val"] > best:
                best = rec["val"]
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        history.append(rec)
        log(json.dumps(rec))
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, history


def save(model: Encoder, fields: tuple[str, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = asdict(model.cfg)
    torch.save({"state": model.state_dict(), "cfg": cfg, "fields": list(fields)}, path)


def load(path: Path, device: torch.device) -> tuple[Encoder, tuple[str, ...]]:
    ck = torch.load(path, map_location=device, weights_only=False)
    cfg = dict(ck["cfg"])
    cfg["drift"] = Drift(**cfg["drift"])
    model = Encoder(len(ck["fields"]), Config(**cfg)).to(device)
    model.load_state_dict(ck["state"])
    return model, tuple(ck["fields"])
