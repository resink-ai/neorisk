import json
from functools import partial

import numpy as np
import polars as pl
import torch
from conftest import BAD, EXCHANGE, HUB

from ethmodel import cli
from ethmodel.data import counterparty_types, events, split_labels
from ethmodel.expand import evaluate, propose, representations
from ethmodel.model import Config, Encoder, mask_tokens
from ethmodel.tokens import CLS, FIELDS, MASK, PAD, PREDICT, encode, pad

SMALL = Config(width=32, layers=1, heads=2, ff=64, cp_dim=4)


def test_masking_never_touches_cls_or_padding(sample):
    seqs = list(encode(events(sample), counterparty_types(sample)).values())
    x = torch.from_numpy(pad(seqs))
    cfg = Config(mask_rate=0.9)
    masked, targets = mask_tokens(x, cfg, torch.Generator().manual_seed(0))
    assert (masked[:, 0] == CLS).all()
    assert (masked[x == PAD] == PAD).all()
    any_target = torch.stack(list(targets.values())).any(0)
    assert any_target.any() and not any_target[:, 0].any()
    for f, where in targets.items():
        assert (masked[..., FIELDS.index(f)][where] == MASK).all()
    assert set(targets) == set(PREDICT)


def test_encoder_shapes_and_padding_do_not_leak(sample):
    seqs = list(encode(events(sample), counterparty_types(sample)).values())[:3]
    model = Encoder(SMALL).eval()
    alone = model(torch.from_numpy(pad(seqs[:1])))[:, 0]
    padded = model(torch.from_numpy(pad(seqs)))[:1, 0]
    assert padded.shape == (1, 32)
    assert torch.allclose(alone, padded, atol=1e-5)


def test_cli_runs_pretrain_embed_expand_and_bench(toy_dir, tmp_path, monkeypatch):
    import ethmodel.model as m

    monkeypatch.setattr(m, "Config", partial(Config, width=32, layers=1, heads=2, ff=64,
                                             cp_dim=4))
    out = tmp_path / "model"
    common = ["--sample", str(toy_dir), "--out", str(out)]
    assert cli.main(["pretrain", *common, "--epochs", "2"]) == 0
    history = json.loads((out / "pretrain.json").read_text())["history"]
    assert len(history) == 2 and all(np.isfinite([h["masked"], h["contrast"]]).all()
                                     for h in history)
    assert cli.main(["embed", *common]) == 0
    emb = pl.read_parquet(out / "embeddings.parquet")
    assert emb.width == 2 + 32 and set(BAD) <= set(emb["address"])
    assert cli.main(["expand", *common, "--k", "5"]) == 0
    results = json.loads((out / "evaluation.json").read_text())
    assert [r["features"] for r in results] == ["embed", "baseline"]
    cand = pl.read_csv(out / "candidates.csv")
    assert cand.height == 5 and not set(cand["address"]) & (set(BAD) | {EXCHANGE})
    assert cli.main(["bench", *common, "--rounds", "2", "--k", "3"]) == 0
    bench = pl.read_csv(out / "bench.csv")
    assert set(bench["method"]) == {"embed", "baseline", "random"} and bench.height == 6


def test_baseline_finds_held_out_bad_addresses_and_explains_candidates(sample, tmp_path):
    split = split_labels(sample)
    reps = representations("baseline", tmp_path, sample, split)
    got = evaluate("baseline", reps, sample, split, k=10)
    assert got["recall@10"] == 1.0 > got["chance@10"]   # the synthetic bad are easy
    cand = propose(reps, sample, split, k=3)
    top = cand.row(0, named=True)
    assert top["address"] == HUB                         # everyone bad pays it
    assert top["kind_guess"] in {"frozen", "phishing"} and top["nearest_labeled"]
    assert top["flows_with_labeled"].startswith("from ")
