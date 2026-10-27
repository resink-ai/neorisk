# ethmodel

v0 of the Ethereum bad-address model: the skeleton from the modeling plan, not a tuned model.
It reads an `eth-collect` sample (default `data/eth/samples/toy/`) and writes to
`data/eth/model/toy/`.

```bash
uv run ethmodel pretrain   # masked event modeling + same-address contrast -> encoder.pt
uv run ethmodel embed      # [CLS] vector per address -> embeddings.parquet
uv run ethmodel expand     # recall@100 on held-out labels (embeddings vs baseline) + candidates.csv
uv run ethmodel bench      # review rounds on bench discover's loop -> bench.csv
```

| step | what it does |
| --- | --- |
| tokens | one token per transfer seen from the address: direction, kind, asset, amount bucket, time-gap bucket, counterparty type, method bucket, hashed counterparty; `[CLS]` in front, latest 127 events |
| body | 4-layer transformer encoder, width 128, about 1.8M parameters (most in the counterparty table); ~1 minute for 20 epochs on a laptop CPU at toy size |
| head | positive-unlabeled logistic regression on embeddings: trust-weighted positives against unlabeled, never assumed good; blended 70/30 with a one-hop graph score (value share of flow with known bad addresses) |
| baseline | 23 hand-built aggregates through the same head |

Rules the code keeps:

- **Held-out labels:** 30% of the high-trust risk addresses (OFAC, stablecoin freezes), fixed by
  `--seed`. They are unknown to every step: no timing cut, not positives, scored like anyone.
- **Timing rule:** a training label's transfers after its `observed_at` day are dropped.
- **Leak guard:** `sample_reason` never reaches the model. It only picks the evaluation pool:
  recall@100 is measured among sampled addresses (seeds + random), because counterparties have
  1-2 transfers and would be told apart by history length alone.
- **Candidates** exclude risk-labeled and service-labeled addresses. Each comes with its
  nearest labeled addresses in embedding space, its largest flows with labeled ones, and a
  `kind_guess` from per-kind heads (kinds with at least 10 positives).
- **Reviewer (v0):** `ethmodel bench` runs `bench discover`'s `run_method` with an oracle that says
  "bad" only for held-out labels. A human or LLM analyst replaces it later.
