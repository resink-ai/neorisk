"""The body: a small transformer encoder over transfer tokens, pre-trained without labels.

Objectives:
  masked event modeling  hide 15% of tokens (80%: the whole token, 20%: one field) and predict
                         direction, kind, amount, gap and counterparty type back
  same-address contrast  two random windows of one address embed close together and far from
                         the other addresses in the batch (InfoNCE on [CLS])
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ethmodel.tokens import FIELDS, MASK, MAX_LEN, PAD, PREDICT, SIZES, SPECIAL, pad


@dataclass
class Config:
    width: int = 128
    layers: int = 4
    heads: int = 4
    ff: int = 256
    cp_dim: int = 16          # the 65,536 counterparty buckets get a narrow table + projection
    dropout: float = 0.1
    mask_rate: float = 0.15
    field_mask_share: float = 0.2
    contrast_weight: float = 0.5
    temperature: float = 0.1


class Encoder(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        d = cfg.width
        self.fields = nn.ModuleDict({
            f: nn.Embedding(SIZES[f] + SPECIAL, d, padding_idx=PAD)
            for f in FIELDS if f != "cp_id"})
        self.cp = nn.Sequential(nn.Embedding(SIZES["cp_id"] + SPECIAL, cfg.cp_dim,
                                             padding_idx=PAD), nn.Linear(cfg.cp_dim, d))
        self.pos = nn.Embedding(MAX_LEN, d)
        layer = nn.TransformerEncoderLayer(d, cfg.heads, cfg.ff, cfg.dropout, batch_first=True,
                                           norm_first=True)
        self.body = nn.TransformerEncoder(layer, cfg.layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.predict = nn.ModuleDict({f: nn.Linear(d, SIZES[f]) for f in PREDICT})
        self.project = nn.Sequential(nn.Linear(d, d), nn.ReLU(), nn.Linear(d, 64))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x [batch, len, fields] -> hidden [batch, len, width]; position 0 is [CLS]."""
        h = sum(self.fields[f](x[..., i]) for i, f in enumerate(FIELDS) if f != "cp_id")
        h = h + self.cp(x[..., FIELDS.index("cp_id")])
        h = h + self.pos(torch.arange(x.shape[1], device=x.device))
        h = self.body(h, src_key_padding_mask=x[..., 0] == PAD)
        return self.norm(h)


def mask_tokens(x: torch.Tensor, cfg: Config, gen: torch.Generator):
    """Returns the masked input and, per predicted field, where to score [batch, len]."""
    real = (x[..., 0] != PAD) & (torch.arange(x.shape[1]) > 0)   # not padding, not [CLS]
    chosen = real & (torch.rand(x.shape[:2], generator=gen) < cfg.mask_rate)
    whole = chosen & (torch.rand(x.shape[:2], generator=gen) >= cfg.field_mask_share)
    one = torch.randint(len(PREDICT), x.shape[:2], generator=gen)
    masked = x.clone()
    targets = {}
    for j, f in enumerate(PREDICT):
        where = whole | (chosen & ~whole & (one == j))
        masked[..., FIELDS.index(f)][where] = MASK
        targets[f] = where
    masked[whole] = MASK     # a whole-token mask hides the unpredicted fields too
    return masked, targets


def masked_loss(model: Encoder, x: torch.Tensor, gen: torch.Generator) -> torch.Tensor:
    masked, targets = mask_tokens(x, model.cfg, gen)
    h = model(masked)
    losses = []
    for f, where in targets.items():
        if where.any():
            truth = x[..., FIELDS.index(f)][where] - SPECIAL
            losses.append(F.cross_entropy(model.predict[f](h[where]), truth))
    return torch.stack(losses).mean() if losses else h.sum() * 0


def windows(seqs: list[np.ndarray], rng: np.random.Generator) -> np.ndarray:
    """One random contiguous window (about 60% of the events, at least 1) per sequence,
    [CLS] kept in front."""
    out = []
    for s in seqs:
        n = len(s) - 1
        w = max(1, round(n * 0.6))
        start = 1 + int(rng.integers(0, n - w + 1))
        out.append(np.concatenate([s[:1], s[start:start + w]]))
    return pad(out)


def contrast_loss(model: Encoder, seqs: list[np.ndarray], rng: np.random.Generator):
    a = model.project(model(torch.from_numpy(windows(seqs, rng)))[:, 0])
    b = model.project(model(torch.from_numpy(windows(seqs, rng)))[:, 0])
    a, b = F.normalize(a, dim=-1), F.normalize(b, dim=-1)
    logits = a @ b.T / model.cfg.temperature
    labels = torch.arange(len(seqs))
    return (F.cross_entropy(logits, labels) + F.cross_entropy(logits.T, labels)) / 2


def pretrain(seqs: dict[str, np.ndarray], out: Path, *, epochs: int = 20, batch: int = 64,
             lr: float = 1e-3, seed: int = 7, cfg: Config | None = None,
             log=print) -> dict:
    """Train on every sequence, save `encoder.pt` and `pretrain.json` under `out`."""
    cfg = cfg or Config()
    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = Encoder(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    names = sorted(seqs)
    history = []
    t0 = time.time()
    for epoch in range(epochs):
        model.train()
        order = rng.permutation(len(names))
        sums = {"masked": 0.0, "contrast": 0.0}
        steps = 0
        for i in range(0, len(order), batch):
            part = [seqs[names[j]] for j in order[i:i + batch]]
            m = masked_loss(model, torch.from_numpy(pad(part)), gen)
            c = contrast_loss(model, part, rng) if len(part) > 1 else m * 0
            loss = m + cfg.contrast_weight * c
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sums["masked"] += m.item()
            sums["contrast"] += c.item()
            steps += 1
        row = {"epoch": epoch + 1, **{k: v / steps for k, v in sums.items()}}
        history.append(row)
        log(f"  epoch {row['epoch']:3d}  masked {row['masked']:.3f}  "
            f"contrast {row['contrast']:.3f}")
    out.mkdir(parents=True, exist_ok=True)
    torch.save({"config": asdict(cfg), "state": model.state_dict()}, out / "encoder.pt")
    summary = {"sequences": len(names), "epochs": epochs, "batch": batch, "lr": lr,
               "seed": seed, "parameters": sum(p.numel() for p in model.parameters()),
               "seconds": round(time.time() - t0, 1), "history": history}
    (out / "pretrain.json").write_text(json.dumps(summary, indent=2))
    return summary


def load(out: Path) -> Encoder:
    p = out / "encoder.pt"
    if not p.exists():
        raise SystemExit(f"no encoder at {p}; run `ethmodel pretrain` first")
    saved = torch.load(p, weights_only=True)
    model = Encoder(Config(**saved["config"]))
    model.load_state_dict(saved["state"])
    return model.eval()


@torch.no_grad()
def embed(model: Encoder, seqs: dict[str, np.ndarray], batch: int = 256) -> dict[str, np.ndarray]:
    """[CLS] vector per address."""
    model.eval()
    names = sorted(seqs)
    out = {}
    for i in range(0, len(names), batch):
        part = names[i:i + batch]
        h = model(torch.from_numpy(pad([seqs[a] for a in part])))[:, 0]
        out.update(zip(part, h.numpy()))
    return out
