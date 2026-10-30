"""Device embedding v3: a factorised embedding on device_profiles.pqt.

The vector is four unit sub-vectors, each from its own field encoder, scaled by sqrt(w_k):

    id    every non-ID field; trained on tmx_fuzzy_device_id groups (mobile) and the web proxy
          entity, with look-alike devices (same spec bucket) as hard negatives
    spec  hardware, OS, GPU, screen, fonts; regressed onto a Fellegi-Sunter field-agreement score
    env   IP city, geo cell, /24 subnet, timezone, network type; regressed onto graded network
          labels (bssid > privateIp + city > subnet + city > city), which are never inputs
    pref  locale, languages, font and accessibility settings; regressed onto their agreement score

so cos(x, y) = sum_k w_k cos_k(x, y). Splits are connected components over tmx, devId, osId and
the web proxy entity, so no device crosses splits.

    uv run python -m devicefp.v3 prepare
    uv run python -m devicefp.v3 train --name factor
    uv run python -m devicefp.v3 train --name mono --arch mono
    uv run python -m devicefp.v3 baseline
"""

from __future__ import annotations

import argparse
import json
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import torch
import torch.nn.functional as F
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.stats import spearmanr
from torch import nn

from devicefp import pairs as pp
from devicefp.v2 import (
    CAT_CAP,
    DATA,
    ID_COLUMNS,
    MIN_COUNT,
    NUM_BINS,
    ROOT,
    FieldEncoder,
    _clean,
    supcon_loss,
)

RUNS = ROOT / "data/devicefp/runs/v3"

# per-session timestamps and paths, raw addresses (kept only as derived /24 and labels), duplicates
DROP_COLUMNS = {
    "create_time", "bootTime", "firstAppInstallTime", "lastAppUpdate", "installPath",
    "appStoreReceipt", "page", "privateIp", "ipv6", "ip_latitude", "ip_longitude",
    "ip_country_name", "ip_country_name_en",
}
SPEC_FIELDS = [
    "platform", "systemName", "systemVersion", "systemModel", "deviceModel", "deviceRealModel",
    "deviceLocalModel", "systemManufacturer", "systemBrand", "hardware", "systemBoard", "product",
    "codeName", "display", "buildNumber", "buildTags", "kernelVersion", "radioVersion",
    "securityPatch", "systemFingerprint", "cpuName", "cpuProcessorName", "processorCount",
    "activeProcessorCount", "physicalMemory", "MemorySize", "diskSpace", "screenWidth",
    "screenHeight", "screenScale", "scaledScreenDensity", "densityDpi", "xdpi", "ydpi", "gpuVendor",
    "gpuRenderer", "hardwareConcurrency", "architecture", "colorGamut", "isHdr", "maxTouchPoints",
    "osFontsHash", "osFontsSize", "fontFamilyNames", "userInterfaceIdiom", "batteryTechnology",
    "proximitySensor", "vendor", "userAgent", "canvas", "headers-order-string-hash",
    "deviceVersionCode", "isSimulator", "isJailbroken",
]
ENV_FIELDS = [
    "ip_city_name", "ip_country_code", "ip_geo_cell", "ip_subnet24", "timeZone",
    "defaultTimeZoneOffset", "dst", "networkType", "vpnInfo",
]
PREF_FIELDS = [
    "user_locale", "locale", "preferredLanguages", "availableLocaleIdsSize", "availableLocaleIdsHash",
    "systemFontSize", "smallSystemFontSize", "buttonFontSize", "labelFontSize", "screenBrightness",
    "reducedMotion", "contrast", "forcedColor", "monochrome", "keyboardConnected", "orientation",
]
# graded network labels for the env factor: the strongest shared key sets the target cosine
ENV_GRADES = (("bssid", 1.0), ("net", 0.5), ("subnet", 0.15), ("city", 0.05))
WEB_PLATFORMS = ["Web", "PC", "Mac"]


def _raw_codes(values: np.ndarray) -> np.ndarray:
    """Exact value codes without any cap; -1 is missing."""
    out = np.full(len(values), -1, dtype=np.int32)
    if values.dtype.kind == "f":
        keyed = ~np.isnan(values)
    else:
        keyed = np.array([v is not None for v in values], dtype=bool)
        values = values.astype(object)
    if keyed.any():
        kept = values[keyed] if values.dtype.kind == "f" else values[keyed].astype(str)
        _, inv = np.unique(kept, return_inverse=True)
        out[keyed] = inv
    return out


def _key(values: np.ndarray) -> np.ndarray:
    return _raw_codes(values).astype(np.int64)


def components_split(n: int, keys: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """70/15/15 split over connected components of rows linked by any shared key."""
    src, dst, offset = [], [], n
    for k in keys:
        rows = np.flatnonzero(k >= 0)
        src.append(rows)
        dst.append(offset + k[rows])
        offset += int(k.max()) + 1 if (k >= 0).any() else 0
    src, dst = np.concatenate(src), np.concatenate(dst)
    graph = coo_matrix((np.ones(len(src), dtype=np.int8), (src, dst)), shape=(offset, offset))
    _, label = connected_components(graph, directed=False)
    comp = label[:n]
    first = np.full(comp.max() + 1, n, dtype=np.int64)
    np.minimum.at(first, comp, np.arange(n))  # name a component by its first row: stable across runs
    h = np.array([zlib.crc32(str(r).encode()) % 100 for r in first])[comp]
    return comp, np.where(h < 70, 0, np.where(h < 85, 1, 2))


def _encode_capped(s: pl.Series, cap: int) -> tuple[np.ndarray, int]:
    """v2's string encoding with a configurable cap: 0 missing, 1 out of vocabulary."""
    arr = s.to_numpy()
    text = np.where(np.array([v is None for v in arr]), "", arr.astype(object)).astype(str)
    uniq, inv, counts = np.unique(text, return_inverse=True, return_counts=True)
    code_of = np.ones(len(uniq), dtype=np.int64)
    code_of[uniq == ""] = 0
    real = np.flatnonzero((uniq != "") & (counts >= MIN_COUNT))
    real = real[np.argsort(-counts[real], kind="stable")][: cap - 2]
    code_of[real] = np.arange(2, 2 + len(real))
    return code_of[inv], cap


def _encode_binned(s: pl.Series, bins: int) -> tuple[np.ndarray, int]:
    """v2's quantile binning with a configurable bin count: 0 missing."""
    x = s.cast(pl.Float64).to_numpy()
    ok = ~np.isnan(x)
    codes = np.zeros(len(x), dtype=np.int64)
    if ok.sum() == 0:
        return codes, 2
    inner = np.unique(np.nanquantile(x[ok], np.linspace(0, 1, bins + 1)))[1:-1]
    codes[ok] = np.searchsorted(inner, x[ok], side="right") + 2
    return codes, int(codes.max()) + 1


def prepare(out: Path = RUNS, data: Path = DATA, bins: int = NUM_BINS, cap: int = CAT_CAP) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    df = pl.read_parquet(data).with_columns(
        pl.concat_str(pl.col("ip_latitude").round(1).cast(pl.String),
                      pl.col("ip_longitude").round(1).cast(pl.String), separator="|").alias("ip_geo_cell"),
        pl.col("privateIp").str.extract(r"^(\d+\.\d+\.\d+)\.\d+$", 1).alias("ip_subnet24"),
    )
    n = df.height

    fields, sizes, codes, raws = [], [], [], []
    for name in df.columns:
        if name in ID_COLUMNS or name in DROP_COLUMNS:
            continue
        s = df[name]
        if s.dtype == pl.Boolean:
            s = s.cast(pl.String)
        if s.dtype == pl.String:
            s = _clean(s)
            c, size = _encode_capped(s, cap)
            raw = _raw_codes(s.to_numpy())
        elif s.dtype.is_numeric():
            c, size = _encode_binned(s, bins)
            raw = _raw_codes(s.cast(pl.Float64).to_numpy())
        else:
            continue
        if size <= 2 or np.unique(c).size <= 1:
            continue
        fields.append(name)
        sizes.append(int(size))
        codes.append(c.astype(np.int32))
        raws.append(raw)
    np.save(out / "codes.npy", np.stack(codes, axis=1))
    np.save(out / "raw.npy", np.stack(raws, axis=1))

    names = ["tmx_fuzzy_device_id", "deviceId", "keychainId", "androidId", "appId", "appSessionId", "osId",
             "gpuRenderer", "deviceModel", "systemModel", "systemVersion", "ip_city_name", "privateIp",
             "ip_subnet24", "bssid", "ssid", "gpuVendor", "platform"]
    lf = pl.DataFrame({c: _clean(df[c]) for c in names}).with_columns(
        df.select(pl.concat_str([pl.col(c).cast(pl.String) for c in ("screenWidth", "screenHeight", "screenScale")],
                                separator="x").alias("screen")).to_series(),
    ).with_columns(
        pl.coalesce("deviceId", "keychainId", "androidId", "appId", "appSessionId").alias("devId"),
        pl.coalesce("deviceModel", "systemModel").alias("model"),
    )

    def joined(*cols: str) -> np.ndarray:
        return _key(lf.select(pl.concat_str([pl.col(c) for c in cols], separator="|")).to_series().to_numpy())

    is_web = df["platform"].is_in(WEB_PLATFORMS).to_numpy()
    tmx = _key(lf["tmx_fuzzy_device_id"].to_numpy())
    devid = _key(lf["devId"].to_numpy())
    osid = np.where(is_web, _key(lf["osId"].to_numpy()), -1)
    proxy = np.where(is_web, joined("osId", "gpuRenderer", "screen"), -1)
    spec = np.where(is_web, joined("platform", "gpuRenderer", "screen"), joined("model", "systemVersion", "screen"))
    entity = np.where(is_web, proxy, tmx)  # identity training entity

    comp, split = components_split(n, [tmx, devid, osid, proxy])
    comp_sizes = np.bincount(comp)

    np.savez(
        out / "labels.npz", tmx=tmx, devid=devid, entity=entity, spec=spec,
        net=joined("privateIp", "ip_city_name"), subnet=joined("ip_subnet24", "ip_city_name"),
        city=_key(lf["ip_city_name"].to_numpy()), bssid=_key(lf["bssid"].to_numpy()),
        ssid=_key(lf["ssid"].to_numpy()), gv=_key(lf["gpuVendor"].to_numpy()),
        is_web=is_web, split=split, comp=comp,
    )
    meta = {
        "rows": n, "bins": bins, "cap": cap, "fields": fields, "field_sizes": sizes, "vocab": int(sum(sizes)),
        "components": len(comp_sizes), "largest_component": int(comp_sizes.max()),
        "split_rows": {k: int((split == i).sum()) for i, k in enumerate(("train", "val", "test"))},
        "split_mobile_rows": {k: int(((split == i) & ~is_web).sum()) for i, k in enumerate(("train", "val", "test"))},
        "split_web_rows": {k: int(((split == i) & is_web).sum()) for i, k in enumerate(("train", "val", "test"))},
        "towers": {k: [f for f in v if f in fields] for k, v in
                (("spec", SPEC_FIELDS), ("env", ENV_FIELDS), ("pref", PREF_FIELDS))},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


# ---------------------------------------------------------------- data


@dataclass
class Data:
    meta: dict
    codes: np.ndarray
    raw: np.ndarray
    lab: dict

    @classmethod
    def load(cls, path: Path = RUNS) -> Data:
        lab = dict(np.load(path / "labels.npz"))
        return cls(json.loads((path / "meta.json").read_text()), np.load(path / "codes.npy"),
                   np.load(path / "raw.npy"), lab)

    def idx(self, fields: list[str]) -> np.ndarray:
        return np.array([self.meta["fields"].index(f) for f in fields])

    def tokens(self, fields: list[str]) -> tuple[torch.Tensor, int]:
        """Token ids for a tower over `fields`, with per-field offsets into one vocabulary."""
        i = self.idx(fields)
        sizes = np.array(self.meta["field_sizes"])[i]
        offsets = np.concatenate([[0], np.cumsum(sizes)[:-1]])
        return torch.from_numpy(self.codes[:, i].astype(np.int64) + offsets[None]), int(sizes.sum())

    def rows(self, split: int, web: bool) -> np.ndarray:
        return np.flatnonzero((self.lab["split"] == split) & (self.lab["is_web"] == web))


# ---------------------------------------------------------------- Fellegi-Sunter match weights


@dataclass
class FS:
    """Per-field m (agree given same device) and value frequencies, fitted on train only."""

    m: np.ndarray
    u: np.ndarray
    freq: list[np.ndarray]

    @classmethod
    def fit(cls, raw: np.ndarray, devid: np.ndarray, train_rows: np.ndarray, seed: int = 0,
            pairs: int = 300_000) -> FS:
        key = np.full(len(devid), -1)
        key[train_rows] = devid[train_rows]
        a, b = pp.GroupPairs(key).sample(pairs, np.random.default_rng(seed))
        ra, rb = raw[a], raw[b]
        both = (ra >= 0) & (rb >= 0)
        m = ((ra == rb) & both).sum(0) / np.maximum(both.sum(0), 1)
        freq, u = [], []
        for f in range(raw.shape[1]):
            v = raw[train_rows, f]
            v = v[v >= 0]
            c = np.bincount(v, minlength=int(raw[:, f].max()) + 1).astype(np.float64)
            p = c / max(c.sum(), 1)
            freq.append(p)
            u.append(float((p ** 2).sum()))
        return cls(np.clip(m, 0.01, 0.999), np.clip(np.array(u), 1e-6, 0.999), freq)

    def field_weights(self) -> np.ndarray:
        """Agreement weight log(m/u), floored at 0: how much a match on this field says."""
        return np.maximum(np.log(self.m / self.u), 0.0)

    def score(self, raw: np.ndarray, a: np.ndarray, b: np.ndarray, chunk: int = 200_000) -> np.ndarray:
        """Log-likelihood ratio of same device, with value-specific agreement weights log(m/p_v)."""
        out = np.zeros(len(a))
        dis = np.log((1 - self.m) / (1 - self.u))
        for s in range(0, len(a), chunk):
            ra, rb = raw[a[s:s + chunk]], raw[b[s:s + chunk]]
            tot = np.zeros(len(ra))
            for f in range(raw.shape[1]):
                both = (ra[:, f] >= 0) & (rb[:, f] >= 0)
                agree = both & (ra[:, f] == rb[:, f])
                p = self.freq[f][np.clip(ra[:, f], 0, len(self.freq[f]) - 1)]
                p = np.where(p > 0, p, 1e-6)
                tot += np.where(agree, np.log(self.m[f] / p), np.where(both, dis[f], 0.0))
            out[s:s + chunk] = tot
        return out


def agreement(raw: np.ndarray, w: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Weighted share of the present fields on which two profiles agree (numpy, for evaluation)."""
    ra, rb = raw[a], raw[b]
    both = (ra >= 0) & (rb >= 0)
    num = (((ra == rb) & both) * w).sum(1)
    den = (both * w).sum(1)
    return np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)


def agreement_matrix(raw: torch.Tensor, w: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Batch version: target and validity for every pair of rows in `raw` (B x F)."""
    a, b = raw[:, None, :], raw[None, :, :]
    both = (a >= 0) & (b >= 0)
    num = (((a == b) & both).float() * w).sum(-1)
    den = (both.float() * w).sum(-1)
    return num / den.clamp(min=1e-12), den > 0


def env_target(lab: dict, rows: np.ndarray) -> np.ndarray:
    t = np.zeros((len(rows), len(rows)), dtype=np.float32)
    for key, grade in reversed(ENV_GRADES):
        k = lab[key][rows]
        same = (k[:, None] == k[None, :]) & (k[:, None] >= 0)
        t[same] = grade
    return t


# ---------------------------------------------------------------- model


class Factorised(nn.Module):
    def __init__(self, towers: dict[str, dict], weights: dict[str, float]):
        super().__init__()
        self.names = list(towers)
        self.towers = nn.ModuleDict({k: FieldEncoder(**cfg) for k, cfg in towers.items()})
        self.weights = weights

    def forward(self, toks: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        return {k: self.towers[k](toks[k]) for k in self.names}


def combine(zs: dict[str, torch.Tensor], w: dict[str, float], train_only: str | None = None) -> torch.Tensor:
    """Concatenate sqrt(w_k) z_k; with `train_only`, the other factors are constants."""
    parts = []
    for k, z in zs.items():
        z = z if train_only is None or k == train_only else z.detach()
        parts.append(z * w[k] ** 0.5)
    return torch.cat(parts, dim=1)


# ---------------------------------------------------------------- batches


class IdentityBatches:
    """P entities x K profiles. With probability `hard`, half the entities share the anchor's spec bucket."""

    def __init__(self, entity, spec, rows, P, K, hard, rng):
        ents, inv, counts = np.unique(entity[rows], return_inverse=True, return_counts=True)
        order = np.argsort(inv, kind="stable")
        sorted_rows, starts = rows[order], np.concatenate([[0], np.cumsum(counts)])
        self.rows_of = {}
        bucket_of = {}
        for j, e in enumerate(ents):
            if counts[j] >= 2 and e >= 0:
                r = sorted_rows[starts[j]:starts[j + 1]]
                self.rows_of[int(e)] = r
                bucket_of[int(e)] = int(spec[r[0]])
        self.entities = np.array(list(self.rows_of))
        by_bucket: dict[int, list] = {}
        for e, b in bucket_of.items():
            if b >= 0:
                by_bucket.setdefault(b, []).append(e)
        self.by_bucket = {b: np.array(v) for b, v in by_bucket.items() if len(v) >= 8}
        self.bucket_of, self.P, self.K, self.hard, self.rng = bucket_of, P, K, hard, rng

    def sample(self) -> tuple[np.ndarray, np.ndarray]:
        rng, P = self.rng, self.P
        anchor = int(rng.choice(self.entities))
        chosen = [anchor]
        pool = self.by_bucket.get(self.bucket_of[anchor])
        if pool is not None and rng.random() < self.hard:
            chosen += list(rng.choice(pool, min(P // 2, len(pool)), replace=False))
        chosen = np.unique(np.concatenate([chosen, rng.choice(self.entities, P)]))[:P]
        rows = [rng.choice(self.rows_of[int(e)], self.K, replace=len(self.rows_of[int(e)]) < self.K) for e in chosen]
        return np.concatenate(rows), np.repeat(chosen, self.K)


class EnvBatches:
    """G network groups (privateIp + city) x K profiles; with probability 1/2 all from one city."""

    def __init__(self, lab, rows, G, K, rng):
        net, city = lab["net"], lab["city"]
        rows = rows[net[rows] >= 0]
        keys, inv, counts = np.unique(net[rows], return_inverse=True, return_counts=True)
        order = np.argsort(inv, kind="stable")
        sorted_rows, starts = rows[order], np.concatenate([[0], np.cumsum(counts)])
        self.groups = [sorted_rows[starts[j]:starts[j + 1]] for j in range(len(keys)) if counts[j] >= 2]
        gcity = np.array([city[g[0]] for g in self.groups])
        by_city: dict[int, list] = {}
        for i, c in enumerate(gcity):
            by_city.setdefault(int(c), []).append(i)
        self.by_city = [np.array(v) for v in by_city.values() if len(v) >= G]
        self.G, self.K, self.rng = G, K, rng

    def sample(self) -> np.ndarray:
        rng = self.rng
        if self.by_city and rng.random() < 0.5:
            pool = self.by_city[rng.integers(len(self.by_city))]
            idx = rng.choice(pool, self.G, replace=False)
        else:
            idx = rng.choice(len(self.groups), self.G, replace=False)
        return np.concatenate([rng.choice(self.groups[i], self.K, replace=len(self.groups[i]) < self.K) for i in idx])


# ---------------------------------------------------------------- evaluation


TEST_SIZES = {"pos": 200_000, "spec": 200_000, "env": 100_000, "rest": 600_000}
VAL_SIZES = {"pos": 60_000, "spec": 60_000, "env": 30_000, "rest": 200_000}


def eval_pairs(d: Data, split: int, sizes: dict, seed: int) -> tuple[pp.PairSet, dict]:
    lab, parts, counts = d.lab, [], {}
    for cls, web in ((0, False), (1, True)):
        ps, c = pp.build_pairs(d.rows(split, web), lab["tmx"], lab["spec"], lab["net"], cls, sizes, seed + cls)
        parts.append(ps)
        counts["web" if web else "mobile"] = c
    return pp.PairSet.concat(parts), counts


@torch.no_grad()
def embed(model: Factorised, toks: dict[str, torch.Tensor], rows: np.ndarray, device: str,
          bs: int = 8192) -> dict[str, torch.Tensor]:
    model.eval()
    out: dict[str, list] = {k: [] for k in model.names}
    for i in range(0, len(rows), bs):
        idx = torch.as_tensor(rows[i:i + bs])
        zs = model({k: toks[k][idx].to(device) for k in model.names})
        for k, z in zs.items():
            out[k].append(z.half())
    return {k: torch.cat(v) for k, v in out.items()}


@torch.no_grad()
def factor_cos(Z: dict[str, torch.Tensor], pos: np.ndarray, a: np.ndarray, b: np.ndarray) -> dict[str, np.ndarray]:
    ia, ib = torch.as_tensor(pos[a]), torch.as_tensor(pos[b])
    out = {}
    for k, z in Z.items():
        vals = []
        for s in range(0, len(ia), 500_000):
            za, zb = z[ia[s:s + 500_000].to(z.device)], z[ib[s:s + 500_000].to(z.device)]
            vals.append((za.float() * zb.float()).sum(1).cpu().numpy())
        out[k] = np.concatenate(vals)
    return out


def mix(cos: dict[str, np.ndarray], w: dict[str, float]) -> np.ndarray:
    return sum(w[k] * cos[k] for k in cos)


def weight_grid(names: list[str]) -> list[dict[str, float]]:
    if names == ["id"]:
        return [{"id": 1.0}]
    grid = []
    for wid in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0):
        for wenv in (0.0, 0.05, 0.1):
            rest = 1.0 - wid - wenv
            if rest < -1e-9:
                continue
            for share in (0.5, 0.75, 1.0):  # of the remainder, the share given to spec
                grid.append({"id": wid, "spec": rest * share, "env": wenv, "pref": rest * (1 - share)})
    return grid


def fit_weights(cos: dict[str, np.ndarray], ps: pp.PairSet, names: list[str]) -> dict[str, float]:
    """Identity weights chosen on validation: best mobile weighted PR AUC."""
    m = ps.cls == 0
    best, best_w = -1.0, None
    for w in weight_grid(names):
        ap = pp.weighted_ap(mix(cos, w)[m], ps.y[m], ps.w[m])
        if ap > best:
            best, best_w = ap, w
    return {k: round(v, 4) for k, v in best_w.items()}


@torch.no_grad()
def knn(z: torch.Tensor, k: int, chunk: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    idx_all, val_all = [], []
    for i in range(0, z.shape[0], chunk):
        sim = z[i:i + chunk].float() @ z.float().T
        r = torch.arange(i, min(i + chunk, z.shape[0]), device=z.device)
        sim[torch.arange(len(r)), r] = -2.0
        v, ix = sim.topk(k, dim=1)
        idx_all.append(ix.cpu().numpy())
        val_all.append(v.cpu().numpy())
    return np.concatenate(idx_all), np.concatenate(val_all)


def bcubed(cluster: np.ndarray, truth: np.ndarray) -> tuple[float, float]:
    _, joint = np.unique(np.stack([cluster, truth], 1), axis=0, return_inverse=True)
    n_joint = np.bincount(joint.ravel())[joint.ravel()]
    n_c = np.bincount(cluster)[cluster]
    _, t_inv = np.unique(truth, return_inverse=True)
    n_t = np.bincount(t_inv)[t_inv]
    return float((n_joint / n_c).mean()), float((n_joint / n_t).mean())


def cluster_metrics(zfull: torch.Tensor, tmx: np.ndarray, t: float, k: int = 20) -> dict:
    """Fingerprint ID = connected components of the cos >= t graph over each row's k neighbours."""
    nb, val = knn(zfull, k)
    n = len(tmx)
    src = np.repeat(np.arange(n), k)
    keep = val.ravel() >= t
    g = coo_matrix((np.ones(keep.sum()), (src[keep], nb.ravel()[keep])), shape=(n, n))
    _, cl = connected_components(g, directed=False)
    p, r = bcubed(cl, tmx)
    _, t_inv, t_cnt = np.unique(tmx, return_inverse=True, return_counts=True)
    has_mate = t_cnt[t_inv] >= 2
    hit10 = (tmx[nb[:, :10]] == tmx[:, None]).any(1)
    return {"threshold": float(t), "bcubed_precision": p, "bcubed_recall": r,
                "bcubed_f1": 2 * p * r / (p + r) if p + r else 0.0,
                "clusters": int(cl.max() + 1), "tmx_ids": len(t_cnt), "largest_cluster": int(np.bincount(cl).max()),
                "largest_tmx": int(t_cnt.max()), "recall_at_10": float(hit10[has_mate].mean()),
                "rows_with_mate": int(has_mate.sum())}


def gold_recall(score_fn, lab: dict, rows: np.ndarray, t: float, seed: int, n: int = 100_000) -> dict:
    """devId-equal pairs are the same device by definition: share above the cutoff."""
    key = np.full(len(lab["devid"]), -1)
    key[rows] = lab["devid"][rows]
    gp = pp.GroupPairs(key)
    if not gp:
        return {}
    a, b = gp.sample(n, np.random.default_rng(seed))
    s = score_fn(a, b)
    return {"pairs": len(a), "recall": float((s >= t).mean()), "median": float(np.median(s)),
                "tmx_equal_share": float((lab["tmx"][a] == lab["tmx"][b]).mean())}


def relatedness(cos_fn, d: Data, fs: FS, rows: np.ndarray, seed: int) -> dict:
    """Spec / pref agreement correlation, gpuVendor separation, network separation, farm cohesion."""
    lab, rng, out = d.lab, np.random.default_rng(seed), {}
    a, b = rng.choice(rows, 200_000), rng.choice(rows, 200_000)
    keep = (a != b) & (lab["tmx"][a] != lab["tmx"][b])
    a, b = a[keep], b[keep]
    cos = cos_fn(a, b)
    w_all = fs.field_weights()
    for name in ("spec", "pref"):
        fi = d.idx(d.meta["towers"][name])
        t = agreement(d.raw[:, fi], w_all[fi], a, b)
        ok = ~np.isnan(t)
        out[f"{name}_spearman"] = {k: float(spearmanr(v[ok], t[ok]).statistic) for k, v in cos.items()}
    gv = lab["gv"]
    ok = (gv[a] >= 0) & (gv[b] >= 0)
    same = (gv[a] == gv[b])[ok].astype(np.int64)
    out["gpuVendor"] = {k: {"auc": pp.weighted_auc(v[ok], same, np.ones(ok.sum())),
                                "mean_same": float(v[ok][same == 1].mean()), "mean_diff": float(v[ok][same == 0].mean())}
                        for k, v in cos.items()}
    out["gpuVendor_pairs"] = {"same": int(same.sum()), "diff": int((1 - same).sum())}

    # network: same privateIp + city (or same bssid) vs same city on another network, all different tmx
    inside = np.zeros(len(lab["tmx"]), bool)
    inside[rows] = True
    city_pairs = pp.GroupPairs(np.where(inside, lab["city"], -1))
    if city_pairs:
        ca, cb = city_pairs.sample(300_000, rng)
        neg = (ca != cb) & (lab["tmx"][ca] != lab["tmx"][cb]) & ~((lab["net"][ca] >= 0) & (lab["net"][ca] == lab["net"][cb]))
        ca, cb = ca[neg][:100_000], cb[neg][:100_000]
        cneg = cos_fn(ca, cb)
        for key in ("net", "bssid"):
            gp = pp.GroupPairs(np.where(inside, lab[key], -1))
            if not gp:
                continue
            pa, pb = gp.sample(200_000, rng)
            m = (pa != pb) & (lab["tmx"][pa] != lab["tmx"][pb])
            pa, pb = pa[m][:100_000], pb[m][:100_000]
            if len(pa) < 50:
                continue
            cpos = cos_fn(pa, pb)
            y = np.concatenate([np.ones(len(pa)), np.zeros(len(ca))]).astype(np.int64)
            out[f"network_{key}"] = {k: {"auc": pp.weighted_auc(np.concatenate([cpos[k], cneg[k]]), y, np.ones(len(y))),
                                             "mean_same": float(cpos[k].mean()), "mean_other": float(cneg[k].mean())}
                                     for k in cpos}
            out[f"network_{key}"]["pairs"] = len(pa)

    # farm candidates: Wi-Fi groups with >= 3 distinct devices (tmx) inside these rows
    groups = []
    for key in ("ssid", "bssid"):
        k = lab[key][rows]
        for g in np.unique(k[k >= 0]):
            r = rows[k == g]
            if len(np.unique(lab["tmx"][r])) >= 3:
                groups.append(r)
    if groups:
        within = {}
        for r in groups:
            ia, ib = np.triu_indices(len(r), 1)
            ga, gb = r[ia], r[ib]
            m = lab["tmx"][ga] != lab["tmx"][gb]
            for kk, v in cos_fn(ga[m], gb[m]).items():
                within.setdefault(kk, []).append(v.mean())
        out["farm_groups"] = {"groups": len(groups), "within_mean": {k: float(np.mean(v)) for k, v in within.items()},
                                  "random_mean": {k: float(v.mean()) for k, v in cos.items()}}
    return out


def full_eval(d: Data, model: Factorised, toks, w: dict, threshold: float, thr_class: dict[str, float],
              ps: pp.PairSet, split: int, device: str, seed: int, fs: FS) -> dict:
    rows_split = np.flatnonzero(d.lab["split"] == split)
    Z = embed(model, toks, rows_split, device)
    pos = _pos(d.lab, split)
    cos = factor_cos(Z, pos, ps.a, ps.b)
    score = mix(cos, w)
    thresholds = {"0.950": 0.95, "0.980": 0.98, "0.990": 0.99, "val_f1": threshold}
    res = {"identity": identity_metrics_by(cos, score, ps, thresholds), "weights": w}
    add_class_cutoffs(res["identity"]["full"], score, ps, thr_class)

    def score_fn(a, b):
        return mix(factor_cos(Z, pos, a, b), w)

    def cos_fn(a, b):
        c = factor_cos(Z, pos, a, b)
        c["full"] = mix(c, w)
        return c

    res["gold"], res["clusters"], res["relatedness"] = {}, {}, {}
    for cls, web in ((0, False), (1, True)):
        name = "web" if web else "mobile"
        rows = d.rows(split, web)
        res["gold"][name] = gold_recall(score_fn, d.lab, rows, thr_class[name], seed)
        zfull = torch.cat([Z[k][torch.as_tensor(pos[rows]).to(device)].float() * w[k] ** 0.5 for k in Z], 1)
        res["clusters"][name] = cluster_metrics(zfull, d.lab["tmx"][rows], thr_class[name])
        res["relatedness"][name] = relatedness(cos_fn, d, fs, rows, seed)
    return res


def add_class_cutoffs(blocks: dict, score: np.ndarray, ps: pp.PairSet, thr_class: dict[str, float]) -> None:
    """Precision and recall at each class's own validation cutoff (pooled uses both)."""
    cut = np.where(ps.cls == 0, thr_class["mobile"], thr_class["web"])
    for name, mask in (("pooled", np.ones(len(ps.a), bool)), ("mobile", ps.cls == 0), ("web", ps.cls == 1)):
        if name in blocks:
            pred, y, w = (score >= cut)[mask], ps.y[mask], ps.w[mask]
            tp = (w * y * pred).sum()
            blocks[name]["at"]["val_f1_class"] = {
                "threshold": thr_class.get(name), "precision": float(tp / max((w * pred).sum(), 1e-12)),
                "recall": float(tp / max((w * y).sum(), 1e-12))}


def identity_metrics_by(cos: dict, score: np.ndarray, ps: pp.PairSet, thresholds: dict) -> dict:
    out = {"full": pp.identity_metrics(score, ps, thresholds)}
    if len(cos) > 1:  # each factor on its own, for the record
        for k, v in cos.items():
            m = pp.identity_metrics(v, ps, {})
            out[k] = {c: {"pr_auc": b["pr_auc"], "roc_auc": b["roc_auc"]} for c, b in m.items()}
    return out


# ---------------------------------------------------------------- training


def tower_configs(d: Data, arch: str) -> tuple[dict, dict, dict[str, list[str]]]:
    if arch == "mono":
        fields = {"id": d.meta["fields"]}
        cfg = {"id": {"d": 64, "out": 128}}
        weights = {"id": 1.0}
    else:
        fields = {"id": d.meta["fields"], **d.meta["towers"]}
        cfg = {"id": {"d": 64, "out": 64}, "spec": {"d": 32, "out": 32}, "env": {"d": 32, "out": 32},
               "pref": {"d": 32, "out": 32}}
        weights = {"id": 0.7, "spec": 0.1, "env": 0.1, "pref": 0.1}
    return fields, cfg, weights


def train(name: str, arch: str = "factor", steps: int = 12000, eval_every: int = 1000, P: int = 128,
          K: int = 4, tau: float = 0.1, lam: float = 0.0, hard: float = 0.5, p_web: float = 0.25,
          web_weight: float = 0.5, lr: float = 1e-3, seed: int = 0, device: str = "cuda",
          path: Path = RUNS, root: Path = RUNS, web_entity: str = "proxy") -> dict:
    """Train on the prepared data in `path`; the run is saved under `root / name`."""
    t0 = time.time()
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    d = Data.load(path)
    lab = d.lab
    entity = np.where(lab["is_web"], lab["tmx"], lab["entity"]) if web_entity == "tmx" else lab["entity"]
    fs = FS.fit(d.raw, lab["devid"], np.flatnonzero(lab["split"] == 0), seed)
    fields, cfg, weights = tower_configs(d, arch)

    toks, towers = {}, {}
    for k, f in fields.items():
        toks[k], vocab = d.tokens(f)
        towers[k] = dict(vocab=vocab, n_fields=len(f), **cfg[k])
    model = Factorised(towers, weights).to(device)
    kernel = {}
    for k in ("spec", "pref"):
        if k in fields:
            fi = d.idx(fields[k])
            kernel[k] = (torch.from_numpy(d.raw[:, fi]), torch.as_tensor(fs.field_weights()[fi], dtype=torch.float32, device=device))

    train_mobile, train_web = d.rows(0, False), d.rows(0, True)
    id_batches = [IdentityBatches(entity, lab["spec"], r, P, K, hard, rng) for r in (train_mobile, train_web)]
    env_batches = EnvBatches(lab, np.flatnonzero(lab["split"] == 0), P, K, rng) if "env" in fields else None

    val_ps, _ = eval_pairs(d, 1, VAL_SIZES, seed=101)
    val_rows = np.flatnonzero(lab["split"] == 1)
    val_pos = np.full(len(lab["tmx"]), -1)
    val_pos[val_rows] = np.arange(len(val_rows))

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.05)
    gv_t = torch.as_tensor(lab["gv"])
    log, best_ap, best_state, best_step = [], -1.0, None, 0
    for step in range(1, steps + 1):
        model.train()
        web = rng.random() < p_web
        rows, ent = id_batches[int(web)].sample()
        idx = torch.as_tensor(rows)
        zs = model({k: toks[k][idx].to(device) for k in model.names})
        z = combine(zs, weights, train_only="id")
        z = F.normalize(z, dim=1)  # already unit length; guards fp drift
        parts = {"id": (web_weight if web else 1.0) * supcon_loss(
            z, torch.as_tensor(ent, device=device), gv_t[idx].to(device), tau, lam)}
        iu = torch.triu_indices(len(rows), len(rows), 1, device=device)
        for k, (raw_k, wk) in kernel.items():
            t, ok = agreement_matrix(raw_k[idx].to(device), wk)
            c = zs[k] @ zs[k].T
            m = ok[iu[0], iu[1]]
            parts[k] = F.mse_loss(c[iu[0], iu[1]][m], t[iu[0], iu[1]][m])
        if env_batches is not None:
            erows = env_batches.sample()
            ez = model.towers["env"](toks["env"][torch.as_tensor(erows)].to(device))
            et = torch.as_tensor(env_target(lab, erows), device=device)
            ie = torch.triu_indices(len(erows), len(erows), 1, device=device)
            parts["env"] = F.mse_loss((ez @ ez.T)[ie[0], ie[1]], et[ie[0], ie[1]])
        loss = sum(parts.values())
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if step % eval_every == 0 or step == steps:
            Z = embed(model, toks, val_rows, device)
            cos = factor_cos(Z, val_pos, val_ps.a, val_ps.b)
            m = val_ps.cls == 0
            s = mix(cos, weights)
            entry = dict(step=step, minutes=round((time.time() - t0) / 60, 1),
                         **{f"loss_{k}": round(v.item(), 4) for k, v in parts.items()},
                         val_mobile_pr_auc=pp.weighted_ap(s[m], val_ps.y[m], val_ps.w[m]),
                         val_web_pr_auc=pp.weighted_ap(s[~m], val_ps.y[~m], val_ps.w[~m]))
            log.append(entry)
            print(json.dumps(entry), flush=True)
            if entry["val_mobile_pr_auc"] > best_ap:
                best_ap, best_step = entry["val_mobile_pr_auc"], step
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    out = root / name
    out.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state": best_state, "towers": towers, "fields": fields, "weights_train": weights, "arch": arch, "best_step": best_step,
        "log": log, "minutes": round((time.time() - t0) / 60, 1), "data": str(path),
        "config": {"steps": steps, "P": P, "K": K, "tau": tau, "lam": lam, "hard": hard, "p_web": p_web, "web_weight": web_weight,
                    "lr": lr, "seed": seed, "web_entity": web_entity, "bins": d.meta.get("bins", NUM_BINS),
                    "cap": d.meta.get("cap", CAT_CAP)},
    }, out / "model.pt")
    return evaluate(name, root=root, device=device, seed=seed)


def evaluate(name: str, root: Path = RUNS, device: str = "cuda", seed: int = 0) -> dict:
    """Refit identity weights and cutoffs on validation, then score the test split once."""
    ck = torch.load(root / name / "model.pt", map_location="cpu", weights_only=False)
    path = Path(ck.get("data", root))
    d = Data.load(path)
    lab = d.lab
    fs = FS.fit(d.raw, lab["devid"], np.flatnonzero(lab["split"] == 0), seed)
    toks = {k: d.tokens(f)[0] for k, f in ck["fields"].items()}
    weights = ck.get("weights_train") or tower_configs(d, "mono" if list(ck["fields"]) == ["id"] else "factor")[2]
    model = Factorised(ck["towers"], weights).to(device)
    model.load_state_dict(ck["state"])

    val_ps, val_counts = eval_pairs(d, 1, VAL_SIZES, seed=101)
    cos_val = factor_cos(embed(model, toks, np.flatnonzero(lab["split"] == 1), device), _pos(lab, 1),
                         val_ps.a, val_ps.b)
    w_fit = fit_weights(cos_val, val_ps, model.names)
    s_val = mix(cos_val, w_fit)
    thr = pp.best_f1_threshold(s_val, val_ps.y, val_ps.w)
    thr_class = {c: pp.best_f1_threshold(s_val[val_ps.cls == i], val_ps.y[val_ps.cls == i], val_ps.w[val_ps.cls == i])
                 for i, c in enumerate(("mobile", "web"))}

    test_ps, test_counts = eval_pairs(d, 2, TEST_SIZES, seed=202)
    test = full_eval(d, model, toks, w_fit, thr, thr_class, test_ps, 2, device, seed, fs)
    s_default = pp.identity_metrics(
        mix(factor_cos(embed(model, toks, np.flatnonzero(lab["split"] == 2), device), _pos(lab, 2),
                       test_ps.a, test_ps.b), weights), test_ps, {})
    result = {
        "name": name, "arch": ck.get("arch"), "best_step": ck.get("best_step"), "weights_train": weights, "weights_fit": w_fit,
        "threshold_val": thr, "threshold_val_class": thr_class, "config": ck.get("config"), "minutes_train": ck.get("minutes"),
        "params": int(sum(p.numel() for p in model.parameters())), "towers": {k: len(v) for k, v in ck["fields"].items()},
        "log": ck.get("log"), "val_identity": pp.identity_metrics(s_val, val_ps, {"val_f1": thr}),
        "val_counts": val_counts, "test_counts": test_counts, "test": test,
        "test_identity_train_weights": {c: {"pr_auc": b["pr_auc"], "roc_auc": b["roc_auc"]} for c, b in s_default.items()},
    }
    (root / name / "result.json").write_text(json.dumps(result, indent=2, default=float))
    return result


def _pos(lab: dict, split: int) -> np.ndarray:
    rows = np.flatnonzero(lab["split"] == split)
    pos = np.full(len(lab["tmx"]), -1)
    pos[rows] = np.arange(len(rows))
    return pos


def baseline(path: Path = RUNS, seed: int = 0) -> dict:
    """Fellegi-Sunter match weights over the same fields, scored on the same val/test pairs."""
    d = Data.load(path)
    lab = d.lab
    fs = FS.fit(d.raw, lab["devid"], np.flatnonzero(lab["split"] == 0), seed)
    val_ps, _ = eval_pairs(d, 1, VAL_SIZES, seed=101)
    test_ps, _ = eval_pairs(d, 2, TEST_SIZES, seed=202)
    s_val = fs.score(d.raw, val_ps.a, val_ps.b)
    # the score is a log-likelihood ratio, so the cutoff grid spans the positives' own score range
    grid = np.unique(np.quantile(s_val[val_ps.y == 1], np.linspace(0, 1, 1001)))
    thr = pp.best_f1_threshold(s_val, val_ps.y, val_ps.w, grid=grid)
    thr_class = {}
    for i, c in enumerate(("mobile", "web")):
        m = val_ps.cls == i
        g = np.unique(np.quantile(s_val[m & (val_ps.y == 1)], np.linspace(0, 1, 1001)))
        thr_class[c] = pp.best_f1_threshold(s_val[m], val_ps.y[m], val_ps.w[m], grid=g)
    s_test = fs.score(d.raw, test_ps.a, test_ps.b)
    res = {"threshold_val": thr, "threshold_val_class": thr_class,
               "test_identity": pp.identity_metrics(s_test, test_ps, {"val_f1": thr}),
               "field_weights": {f: float(w) for f, w in zip(d.meta["fields"], fs.field_weights())},
               "m": {f: float(v) for f, v in zip(d.meta["fields"], fs.m)}}
    add_class_cutoffs(res["test_identity"], s_test, test_ps, thr_class)
    res["gold"] = {}
    for web in (False, True):
        rows, c = d.rows(2, web), "web" if web else "mobile"
        res["gold"][c] = gold_recall(lambda a, b: fs.score(d.raw, a, b), lab, rows, thr_class[c], seed)
    (path / "baseline_fs.json").write_text(json.dumps(res, indent=2, default=float))
    return res


def main() -> None:
    p = argparse.ArgumentParser(prog="devicefp.v3")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare")
    pr.add_argument("--out", type=Path, default=RUNS)
    pr.add_argument("--bins", type=int, default=NUM_BINS)
    pr.add_argument("--cap", type=int, default=CAT_CAP)
    sub.add_parser("baseline")
    e = sub.add_parser("evaluate")
    e.add_argument("--name", required=True)
    t = sub.add_parser("train")
    t.add_argument("--name", required=True)
    t.add_argument("--arch", choices=["factor", "mono"], default="factor")
    t.add_argument("--steps", type=int, default=12000)
    t.add_argument("--P", type=int, default=128)
    t.add_argument("--K", type=int, default=4)
    t.add_argument("--tau", type=float, default=0.1)
    t.add_argument("--lam", type=float, default=0.0)
    t.add_argument("--hard", type=float, default=0.5)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--data", type=Path, default=RUNS, help="prepared data directory")
    t.add_argument("--web-entity", choices=["proxy", "tmx"], default="proxy")
    args = p.parse_args()
    if args.cmd == "prepare":
        meta = prepare(args.out, bins=args.bins, cap=args.cap)
        print(json.dumps({k: v for k, v in meta.items() if k not in ("fields", "field_sizes", "towers")}, indent=2))
    elif args.cmd == "baseline":
        r = baseline()
        print(json.dumps({k: r[k] for k in ("threshold_val", "test_identity", "gold")}, indent=2, default=float))
    else:
        if args.cmd == "evaluate":
            r = evaluate(args.name)
        else:
            r = train(args.name, arch=args.arch, steps=args.steps, P=args.P, K=args.K, tau=args.tau, lam=args.lam,
                      hard=args.hard, lr=args.lr, seed=args.seed, path=args.data, web_entity=args.web_entity)
        print(json.dumps({k: r[k] for k in ("best_step", "weights_fit", "threshold_val", "threshold_val_class",
                                             "minutes_train")}, indent=2))
        print(json.dumps(r["test"]["identity"]["full"], indent=2, default=float))


if __name__ == "__main__":
    main()
