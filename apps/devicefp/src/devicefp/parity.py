"""Score embeddings from the native engine on the v3 test pairs, next to the PyTorch reference.

The engine writes the combined vector concat_k sqrt(w_k) z_k, so a pair's v3 score is a dot
product. Same pairs (seed 202) and metric as v3.evaluate.

    uv run python -m devicefp.parity --emb rust_cpu_precision.f32 --emb rust_gpu_recall.f32
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from devicefp import pairs as pp
from devicefp import v3
from devicefp.export import SERVE


def scores(z: np.ndarray, pos: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out = np.empty(len(a))
    for s in range(0, len(a), 500_000):
        za, zb = z[pos[a[s:s + 500_000]]], z[pos[b[s:s + 500_000]]]
        out[s:s + 500_000] = (za.astype(np.float64) * zb).sum(1)
    return out


def check(run: str, files: list[Path], bundle: Path = SERVE) -> dict:
    d = v3.Data.load(v3.RUNS)
    ps, _ = v3.eval_pairs(d, 2, v3.TEST_SIZES, seed=202)
    pos = v3._pos(d.lab, 2)
    golden = bundle / run / "golden"
    dim = json.loads((bundle / run / "encoder.json").read_text())["dim"]
    ref = np.fromfile(golden / "test_fp32.f32", dtype="<f4").reshape(-1, dim)
    s_ref = scores(ref, pos, ps.a, ps.b)
    mob = ps.cls == 0
    out = {}
    for name, z in [("pytorch fp32", ref)] + [(f.name, np.fromfile(f, dtype="<f4").reshape(-1, dim)) for f in files]:
        s = scores(z, pos, ps.a, ps.b)
        diff = np.abs(s - s_ref)
        # Many web pairs have identical inputs, so their exact scores tie; float noise of 1e-7 then
        # decides their order and moves web PR AUC by several points. Scores rounded to 1e-4 keep
        # those ties as ties, which is the comparison that means something across engines.
        r = np.round(s, 4)
        out[name] = {"mobile_pr_auc": round(pp.weighted_ap(s[mob], ps.y[mob], ps.w[mob]), 4),
                     "web_pr_auc": round(pp.weighted_ap(s[~mob], ps.y[~mob], ps.w[~mob]), 4),
                     "mobile_pr_auc_1e-4": round(pp.weighted_ap(r[mob], ps.y[mob], ps.w[mob]), 4),
                     "web_pr_auc_1e-4": round(pp.weighted_ap(r[~mob], ps.y[~mob], ps.w[~mob]), 4),
                     "score_diff_p99": float(np.quantile(diff, 0.99)), "score_diff_max": float(diff.max())}
    return out


def main() -> None:
    p = argparse.ArgumentParser(prog="devicefp.parity")
    p.add_argument("--run", default="factor_tmxweb_s1")
    p.add_argument("--emb", type=Path, action="append", default=[], help="engine output, test rows x dim f32")
    args = p.parse_args()
    print(json.dumps(check(args.run, args.emb), indent=2))


if __name__ == "__main__":
    main()
