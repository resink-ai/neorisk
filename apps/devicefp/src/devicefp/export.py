"""Export a trained v3 run for the native engine in apps/devicefp/serve.

The bundle holds everything needed to go from a raw JSON profile to the v3 embedding:

    encoder.json        per-field vocabularies and bin edges, derived-field rules, tower layout
    model.safetensors   the run's weights, fp32
    golden/             profiles.jsonl (every profile, raw input columns), codes.i32 (the expected
                        field codes), test_rows.i64 + test_fp32.f32 (PyTorch fp32 embeddings)

The vocabularies are rebuilt from device_profiles.pqt with the rules v3.prepare used, and the
export refuses to write unless they reproduce the prepared codes exactly.

    uv run python -m devicefp.export --run factor_tmxweb_s1
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np
import polars as pl
import torch

from devicefp import v3
from devicefp.v2 import CAT_CAP, MIN_COUNT, NUM_BINS, PLACEHOLDERS, _clean

SERVE = v3.ROOT / "data/devicefp/serve/v3"
LAYER_NORM_EPS = 1e-5  # nn.TransformerEncoderLayer and nn.LayerNorm defaults
SUBNET24 = r"^(\d+\.\d+\.\d+)\.\d+$"
DERIVED = {
    "ip_geo_cell": {"kind": "geo_cell", "lat": "ip_latitude", "lon": "ip_longitude", "decimals": 1, "sep": "|"},
    "ip_subnet24": {"kind": "regex", "from": "privateIp", "pattern": SUBNET24},
}


def derive(df: pl.DataFrame) -> pl.DataFrame:
    """The two derived columns, exactly as v3.prepare builds them."""
    return df.with_columns(
        pl.concat_str(pl.col("ip_latitude").round(1).cast(pl.String),
                      pl.col("ip_longitude").round(1).cast(pl.String), separator="|").alias("ip_geo_cell"),
        pl.col("privateIp").str.extract(SUBNET24, 1).alias("ip_subnet24"),
    )


def categorical_vocab(s: pl.Series, cap: int) -> tuple[dict[str, int], np.ndarray]:
    """v3._encode_capped, also returning the value -> code map (0 missing, 1 out of vocabulary)."""
    arr = s.to_numpy()
    text = np.where(np.array([v is None for v in arr]), "", arr.astype(object)).astype(str)
    uniq, inv, counts = np.unique(text, return_inverse=True, return_counts=True)
    code_of = np.ones(len(uniq), dtype=np.int64)
    code_of[uniq == ""] = 0
    real = np.flatnonzero((uniq != "") & (counts >= MIN_COUNT))
    real = real[np.argsort(-counts[real], kind="stable")][: cap - 2]
    code_of[real] = np.arange(2, 2 + len(real))
    return {str(uniq[i]): int(code_of[i]) for i in real}, code_of[inv]


def numeric_edges(s: pl.Series, bins: int) -> tuple[list[float], np.ndarray]:
    """v3._encode_binned, also returning the inner edges: code = 2 + #{edges <= x}, 0 missing."""
    x = s.cast(pl.Float64).to_numpy()
    ok = ~np.isnan(x)
    codes = np.zeros(len(x), dtype=np.int64)
    inner = np.unique(np.nanquantile(x[ok], np.linspace(0, 1, bins + 1)))[1:-1]
    codes[ok] = np.searchsorted(inner, x[ok], side="right") + 2
    return [float(e) for e in inner], codes


def raw_type(dtype: pl.DataType) -> str:
    if dtype == pl.Boolean:
        return "bool"
    if dtype == pl.String:
        return "string"
    return "int" if dtype.is_integer() else "float"


def build_encoder(df: pl.DataFrame, meta: dict, codes: np.ndarray, cap: int, bins: int) -> list[dict]:
    fields = []
    for j, name in enumerate(meta["fields"]):
        s = df[name]
        spec = {"name": name, "size": int(meta["field_sizes"][j]), "raw": raw_type(s.dtype)}
        if name in DERIVED:
            spec["derived"] = DERIVED[name]
        if s.dtype in (pl.Boolean, pl.String):
            vocab, c = categorical_vocab(_clean(s.cast(pl.String)), cap)
            spec.update(kind="cat", vocab=vocab)
        else:
            edges, c = numeric_edges(s, bins)
            spec.update(kind="num", edges=edges)
        if not np.array_equal(c, codes[:, j]):
            raise ValueError(f"field {name}: rebuilt codes differ from the prepared codes")
        fields.append(spec)
    return fields


def write_safetensors(path: Path, tensors: dict[str, torch.Tensor]) -> None:
    """Minimal safetensors writer: 8-byte header length, JSON header, raw little-endian data."""
    header, blobs, offset = {}, [], 0
    for name, t in tensors.items():
        b = t.detach().to(torch.float32).contiguous().numpy().astype("<f4").tobytes()
        header[name] = {"dtype": "F32", "shape": list(t.shape), "data_offsets": [offset, offset + len(b)]}
        blobs.append(b)
        offset += len(b)
    h = json.dumps(header, separators=(",", ":")).encode()
    h += b" " * (-len(h) % 8)
    with path.open("wb") as f:
        f.write(struct.pack("<Q", len(h)))
        f.write(h)
        for b in blobs:
            f.write(b)


@torch.no_grad()
def reference_embeddings(ck: dict, d: v3.Data, w: dict, rows: np.ndarray, device: str) -> np.ndarray:
    """PyTorch fp32 (TF32 off) combined vectors: concat_k sqrt(w_k) z_k, in tower order."""
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    model = v3.Factorised(ck["towers"], ck["weights_train"]).to(device).eval()
    model.load_state_dict(ck["state"])
    toks = {k: d.tokens(f)[0] for k, f in ck["fields"].items()}
    out = []
    for i in range(0, len(rows), 8192):
        idx = torch.as_tensor(rows[i:i + 8192])
        zs = model({k: toks[k][idx].to(device) for k in model.names})
        out.append(torch.cat([zs[k] * w[k] ** 0.5 for k in model.names], 1).float().cpu())
    return torch.cat(out).numpy()


def export(run: str, out: Path = SERVE, runs: Path = v3.RUNS, device: str = "cuda") -> dict:
    ck = torch.load(runs / run / "model.pt", map_location="cpu", weights_only=False)
    result = json.loads((runs / run / "result.json").read_text())
    d = v3.Data.load(Path(ck.get("data", runs)))
    meta = d.meta
    df = derive(pl.read_parquet(v3.DATA))
    cfg = ck.get("config", {})
    fields = build_encoder(df, meta, d.codes, meta.get("cap", cfg.get("cap", CAT_CAP)), meta.get("bins", cfg.get("bins", NUM_BINS)))

    w = result["weights_fit"]
    towers = []
    for k, f in ck["fields"].items():
        cfg = ck["towers"][k]
        towers.append({"name": k, "fields": f, "d": cfg["d"], "out": cfg["out"], "heads": 4, "layers": 2,
                       "vocab": cfg["vocab"], "weight": w[k]})
    encoder = {
        "format": 1, "model": f"devicefp-v3/{run}", "placeholders": sorted(PLACEHOLDERS),
        "layer_norm_eps": LAYER_NORM_EPS, "dim": sum(t["out"] for t in towers), "fields": fields, "towers": towers,
    }
    target = out / run
    (target / "golden").mkdir(parents=True, exist_ok=True)
    (target / "encoder.json").write_text(json.dumps(encoder))
    write_safetensors(target / "model.safetensors", ck["state"])

    # golden input: every profile's raw input columns, in file order, as the service would receive them
    inputs = [f["name"] for f in fields if "derived" not in f] + ["ip_latitude", "ip_longitude", "privateIp"]
    pl.read_parquet(v3.DATA, columns=inputs).write_ndjson(target / "golden/profiles.jsonl")
    d.codes.astype("<i4").tofile(target / "golden/codes.i32")
    test_rows = np.flatnonzero(d.lab["split"] == 2)
    test_rows.astype("<i8").tofile(target / "golden/test_rows.i64")
    reference_embeddings(ck, d, w, test_rows, device).astype("<f4").tofile(target / "golden/test_fp32.f32")
    return {"out": str(target), "fields": len(fields), "dim": encoder["dim"], "profiles": int(d.codes.shape[0]),
            "test_rows": len(test_rows), "weights": w}


def main() -> None:
    p = argparse.ArgumentParser(prog="devicefp.export")
    p.add_argument("--run", default="factor_tmxweb_s1")
    p.add_argument("--out", type=Path, default=SERVE)
    p.add_argument("--device", default="cuda")
    args = p.parse_args()
    print(json.dumps(export(args.run, args.out, device=args.device), indent=2))


if __name__ == "__main__":
    main()
