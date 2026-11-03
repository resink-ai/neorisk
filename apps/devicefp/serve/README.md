# devicefp-serve

Native inference for the v3 factorised device embedding (`devicefp.v3`, run `factor_tmxweb_s1`):
JSON device profile in, 160-d vector out, on Intel CPUs or NVIDIA GPUs. The vector is
`concat_k sqrt(w_k) z_k` over the four factors (id, spec, env, pref) with the weights fitted on
validation, so the dot product of two vectors is the v3 similarity score. Weights are the trained
ones, unchanged.

```bash
# 1. export the run: encoder vocabularies + bin edges, weights, golden files (once per run)
uv run python -m devicefp.export --run factor_tmxweb_s1      # -> data/devicefp/serve/v3/factor_tmxweb_s1/

# 2. build (Rust >= 1.89; CUDA is loaded at run time, no toolkit needed to build)
cd apps/devicefp/serve && cargo build --release               # --no-default-features for a CPU-only build

# 3. serve
B=data/devicefp/serve/v3/factor_tmxweb_s1
export LD_LIBRARY_PATH=$PWD/.venv/lib/python3.12/site-packages/nvidia/cu13/lib   # GPU only: libcublas, libnvrtc
apps/devicefp/serve/target/release/devicefp-serve --bundle $B --engine gpu    # or --engine cpu
```

```text
POST /v1/embed  {"mode": "precision", "profiles": [{"platform": "iOS", "deviceModel": "iPhone14,5", ...}, ...]}
-> 200          {"model": "devicefp-v3/factor_tmxweb_s1", "mode": "precision", "dim": 160, "embeddings": [[...], ...]}
GET  /healthz   {"model": ..., "engine": "gpu (NVIDIA GeForce RTX 2070, sm_75)", "dim": 160}
```

A profile is an object keyed by the `device_profiles.pqt` column names. Unknown keys are ignored,
absent keys count as missing. `mode` defaults to `precision`. One request carries 1 to 4,096
profiles (`--max-request`).

- `precision`: fp32 everywhere, within float noise of PyTorch (max element error 3.5e-7).
- `recall`: fp16 on the GPU (tensor cores, fp32 accumulation, max element error 5.5e-4). On a CPU
  it runs the fp32 path; see "Recall mode on CPU" below.

## Measured (RTX 2070 8 GB, i9-9900K 8 cores / 16 threads, AVX2)

Model only, 128,833 test profiles already encoded:

| engine | profiles/s | vs PyTorch on the same device | max error vs PyTorch fp32 |
| --- | ---: | ---: | ---: |
| PyTorch fp32 GPU (eager, batch 1024) | 29,144 | 1.0x | - |
| **GPU precision** (batch 2048) | **108,510** | 3.7x | 2.5e-7 |
| **GPU recall** (batch 2048) | **186,147** | 6.4x | 4.5e-4 |
| PyTorch fp32 CPU (16 threads, batch 1024) | 2,817 | 1.0x | - |
| **CPU precision** (16 threads) | **24,112** | 8.6x | 3.5e-7 |

Service end to end (HTTP, JSON parse and encode, batching, JSON response), one profile per request,
load generator on the same machine (measured before the fused bias epilogue, which raises GPU recall
model throughput from 136K to 186K profiles/s):

| engine | at 10,000 req/s: p50 / p99 | saturated req/s | idle latency p50 | batch-256 requests |
| --- | --- | ---: | ---: | ---: |
| GPU precision | 1.78 / 2.54 ms | 49,861 | 0.47 ms | 90,061 profiles/s |
| GPU recall | 1.49 / 2.81 ms | 66,448 | 0.42 ms | 102,733 profiles/s |
| CPU | 3.81 / 5.78 ms | 16,489 | 0.60 ms | 21,811 profiles/s |

Encoding alone runs at 357K profiles/s on 16 threads, so it never limits the service.

```bash
target/release/devicefp-load --profiles $B/golden/profiles.jsonl --rate 10000 --concurrency 64 --mode recall
```

## How it is faster

Each tower is a 2-layer pre-norm transformer over one token per field plus CLS. Two exact rewrites
(`src/model.rs`) remove about half the work:

- **Layer-1 tables.** Up to the first attention, a token depends only on its field and value, so
  `value + field` embedding and its LayerNorm'd Q/K/V are precomputed for every vocabulary entry
  and gathered at inference. This is the v3 equivalent of a KV cache.
- **CLS-only last layer.** Only the CLS output is used, so layer 2 computes K/V for every token
  but the query, attention output, residual and FFN for the CLS row only.

Then per target:

- **CPU** (`src/cpu.rs`, `src/math.rs`): `gemm` crate GEMMs, which pick AVX-512 or AVX2+FMA at run
  time. Attention runs as strided GEMMs reading head columns in place. Softmax uses a vectorised
  Cephes exp, with max and sum over 8 lanes; a single running float reduction keeps LLVM from
  vectorising. Profiles go 2 per task, so a task's activations stay in its core's share of L3
  (24K/s at 2 versus 14K/s at 16 per task).
- **GPU** (`src/gpu.rs`, `kernels/v3.cu`): kernels are compiled at start-up with NVRTC for the
  device's own architecture. A fused attention kernel stages each head's K and V in shared memory
  with an online softmax; cuBLAS handles the projections and FFN. In recall mode the fp16 GEMMs
  add bias and ReLU in the cuBLASLt epilogue, with the algorithm autotuned per shape at start-up
  (+33%); fp32 stays on SGEMM plus a bias kernel, which is faster there. Each (mode, batch-size bucket) is
  captured once as a CUDA graph, so a call costs one copy in, one graph launch and one copy out.
  Precision mode runs cuBLAS in pedantic math, so TF32 stays off on Ampere and newer (A10).
- **Service** (`src/service.rs`): handlers parse and encode on tokio; one engine thread takes the
  first queued job plus whatever else is already waiting, up to `--max-batch`. Batches grow by
  themselves under load, and a lone request runs at once. `--max-wait-us` can trade latency for
  fuller batches.

## Verification

```bash
target/release/devicefp-check encode --bundle $B                                  # all 859,109 profiles
target/release/devicefp-check embed --bundle $B --engine gpu --mode recall --out /tmp/gpu_recall.f32
uv run python -m devicefp.parity --emb /tmp/gpu_recall.f32                        # v3 test-pair PR AUC
cargo test --release                                                              # unit + reference tests
```

- **Encoder:** the export rebuilds every vocabulary and bin edge with v3's rules and refuses to
  write unless they reproduce the prepared codes. The Rust encoder then reproduces all 95,361,099
  training codes from the raw JSON. That covers polars' half-to-even rounding, its float
  formatting in `ip_geo_cell`, the `ip_subnet24` regex and the placeholder cleaning.
- **Model:** per-element and per-vector agreement with PyTorch fp32 on the whole test split (table
  above). `tests/forward.rs` checks the restructured forward against a direct f64 transformer.
- **Quality:** on the v3 test pairs, mobile PR AUC is 0.8252 for PyTorch and every engine and
  mode. Web PR AUC is not a usable parity metric. Half of the web positive pairs have identical
  inputs, so their scores tie exactly, and float noise of 1e-7 decides their order and moves web
  PR AUC between 0.37 and 0.50. With scores rounded to 1e-4 (ties kept), PyTorch and all engines
  agree exactly: mobile 0.8249, web 0.4348.

## Recall mode on CPU

Reduced precision only pays off on a CPU with bf16 or int8 dot-product units (AMX, AVX512-BF16,
VNNI). This CPU has none of them. After the rewrites, attention takes about half the CPU time and
GEMMs about a third. The study's int8 path (`src/qgemm.rs`, AVX2 `vpmaddwd`, per-row activation
and per-column weight scales) runs its GEMMs 1.35-1.47x faster but gains only 1.08x end to end
(26.3K vs 24.3K profiles/s) at 8e-3 max error. Recall mode therefore runs the fp32 kernels on CPU
(`devicefp-check --recall i8` measures the int8 path). Because `gemm` dispatches at run time, an AVX-512 server gets
the faster fp32 kernels with no change.

## Optimisation study

`devicefp-check embed` and `sweep` take switches that turn each optimisation off (`--no-tables`,
`--no-cls-only`, `--no-fused-attn`, `--no-graphs`, `--no-fused-bias`), choose recall number formats
(`--recall f32|f16|i8`, `--recall-tables f32|f16|i8`) and time each stage (`--profile`). Throughput
at batch 2048 on the test split; every precision variant stays within 3.7e-7 of PyTorch.

Each optimisation removed from the full engine, and the engine built up from none:

| engine | all on | without graphs | without fused attention | without tables | without CLS-only | without fused bias | none |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GPU precision | 110K | 110K | 80K | 96K | 68K | - | 43K |
| GPU recall | 186K | 186K | 130K | 179K | 128K | 140K | 58K |
| CPU precision | 24.3K | - | - | 21.6K | 13.4K | - | 12.6K |

CUDA graphs matter only for small batches (batch 1: 0.33 vs 0.36 ms). CPU profiles per task:
1 → 24.0K, 2 → 24.2K, 4 → 19.5K, 8 → 16.9K, 64 → 11.2K.

Recall number formats (mobile PR AUC on scores rounded to 1e-4; fp32 is 0.8249):

| engine | compute | tables | profiles/s | max error | mobile PR AUC |
| --- | --- | --- | ---: | ---: | ---: |
| GPU | fp16 (default) | fp16 | 186K | 4.5e-4 | 0.8249 |
| GPU | fp16 | int8 | 183K | 4.7e-3 | 0.8248 |
| GPU | int8 GEMMs | fp16 | 116K | 7.3e-3 | 0.8245 |
| GPU | int8 GEMMs | int8 | 114K | 8.8e-3 | 0.8243 |
| CPU | fp32 | int8 | 19.4K | 4.5e-3 | 0.8247 |
| CPU | int8 GEMMs | fp32 | 26.3K | 8.3e-3 | 0.8244 |
| CPU | int8 GEMMs | int8 | 20.8K | 8.0e-3 | 0.8246 |

On the GPU, int8 loses to fp16: these GEMMs are small and memory-bound, and the separate quantise
and dequantise kernels cost more than the int8 GEMMs save. Smaller tables save memory but not
time. Stage shares: GPU fp16 attention 41%, GEMM 18%, bias and activation 25% (before fusion);
CPU fp32 attention 53%, GEMM 34%, LayerNorm 8.5%.

Batch size (p50 latency per call / profiles/s):

| engine | batch 1 | batch 64 | batch 2048 |
| --- | --- | --- | --- |
| GPU fp32 | 0.33 ms / 3.0K | 1.0 ms / 64K | 18.6 ms / 110K |
| GPU fp16 | 0.25 ms / 4.0K | 0.65 ms / 99K | 11.0 ms / 187K |
| GPU int8 GEMMs | 0.38 ms / 2.6K | 0.96 ms / 67K | 17.7 ms / 116K |
| CPU fp32 | 0.38 ms / 2.6K | 2.7 ms / 23.5K | 85 ms / 24.1K |

CPU threads at batch 4096: 1 → 2.6K, 2 → 5.1K, 4 → 10.1K, 8 → 20.0K, 16 → 24.3K profiles/s
(linear to the 8 physical cores, +22% from hyperthreads).
