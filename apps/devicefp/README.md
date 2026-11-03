# devicefp

v1 of the device fingerprinting model. It embeds a device profile (user-agent, screen, GPU,
canvas, fonts, network, VPN, battery, ...) as a unit vector, so fingerprints of the same device
are close in euclidean distance, similar devices closer than dissimilar ones, and different
devices far apart. Design, data and results: [docs/research/device-fingerprint-model.md](../../docs/research/device-fingerprint-model.md).
Data sources: [docs/research/device-fingerprint-data-sources.md](../../docs/research/device-fingerprint-data-sources.md).

```bash
uv run devicefp prepare                       # FP-Stalker dump -> data/devicefp/fpstalker/
uv run devicefp synth                         # synthetic modern devices -> data/devicefp/synth/
uv run devicefp baselines                     # mismatch count and naive Bayes on the 5 folds
uv run devicefp cv --name final               # train + evaluate, 5 folds over devices
uv run devicefp geometry --name final         # distances in the embedding space
uv run devicefp report                        # markdown table: every run vs the baselines
```

Add `--data data/devicefp/synth` to any step to run it on the synthetic set. Raw downloads go in
`data/devicefp/raw/` (the doc's Reproduce section has the commands).

| module | what it does |
| --- | --- |
| ingest | reads FP-Stalker's MySQL dump as text (never executed) -> parquet |
| profiles | one table shape for every source: device, seen_at, group, scalar and set fields |
| synth | modern devices: real intoli configurations + simulated hardware, network, VPN, battery, drift, spoofers |
| features | `field=value` tokens hashed into 2^18 buckets; drift augmentation |
| model | two-channel encoder (frozen per-value identity codes x learned field weights, plus a transformer channel), SupCon training |
| evaluate | device splits, the hamming and naive Bayes baselines, track / enroll / verify protocols |
| experiment | one fold end to end, fold summaries, run comparison |
| geometry | same vs different distances, distance by number of differing fields |

Rules the code keeps:

- **Devices are split, not fingerprints:** a test device is never seen in training.
  Spoofers (FP-Stalker's countermeasure browsers, the synthetic anti-detect devices) are never
  trained on.
- **Selection on validation only:** the best epoch, the open-set threshold and every config
  choice use validation devices; test is reported, not tuned on.
- **Naive Bayes is the bar:** the identity channel starts from its weights, and every run is
  reported as a paired per-fold difference with it.

## Serving v3

`python -m devicefp.export` writes a run as a self-contained bundle (encoder vocabularies and bin
edges, weights, golden files). [serve/](serve/README.md) is the Rust engine and HTTP service that
embeds raw JSON profiles from it on CPU or GPU, checked against PyTorch with
`python -m devicefp.parity`.
