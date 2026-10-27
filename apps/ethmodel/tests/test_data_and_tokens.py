from datetime import UTC, date, datetime

import numpy as np
import polars as pl
from conftest import BAD, EXCHANGE, HUB, addr, transfer

from ethmodel.data import Sample, counterparty_types, events, split_labels
from ethmodel.features import NAMES, table
from ethmodel.head import graph_scores, rank01, recall_at
from ethmodel.tokens import CLS, FIELDS, MAX_LEN, PAD, SPECIAL, amount_bucket, encode, gap_bucket


def test_split_holds_out_only_high_trust_and_is_repeatable(sample):
    a, b = split_labels(sample, seed=3), split_labels(sample, seed=3)
    assert a.holdout == b.holdout and len(a.holdout) == round(14 * 0.3)
    assert a.holdout <= set(BAD[:14])                 # the 0.9-trust ones
    assert not a.holdout & set(a.train) and len(a.train) == 20 - len(a.holdout)


def test_events_see_both_sides_and_cut_known_labels_after_observed_at():
    t = datetime(2026, 9, 1, tzinfo=UTC)
    a, b = addr(1), addr(2)
    tr = pl.DataFrame([transfer(1, a, b, t, eth=1.0),
                       transfer(2, a, b, datetime(2026, 10, 5, tzinfo=UTC), eth=1.0),
                       transfer(3, a, a, t, eth=1.0)],
                      schema_overrides={"ts": pl.Datetime("us", "UTC")}, infer_schema_length=None)
    labels = pl.DataFrame([{"address": a, "label_kind": "scam", "is_risk": True, "source": "s",
                            "source_ref": None, "trust": 0.3, "observed_at": date(2026, 10, 1),
                            "date_known": True}])
    s = Sample(pl.DataFrame({"address": [a, b], "is_contract": [False, None]}), tr, labels)
    ev = events(s)
    assert ev.filter(pl.col("owner") == a)["direction"].to_list() == ["out", "self", "out"]
    assert ev.filter(pl.col("owner") == b)["direction"].to_list() == ["in", "in"]
    cut = events(s, known={a: 0.3})
    assert cut.filter(pl.col("owner") == a).height == 2      # the Oct 5 transfer is gone
    assert cut.filter(pl.col("owner") == b).height == 2      # b is not labeled


def test_tokens_start_with_cls_and_keep_the_latest_events(sample, monkeypatch):
    import ethmodel.tokens as tok

    seqs = encode(events(sample), counterparty_types(sample))
    s = seqs[BAD[0]]
    assert (s[0] == CLS).all() and len(s) == 11 and s.shape[1] == len(FIELDS)
    assert s[1, FIELDS.index("gap")] == SPECIAL       # first event: gap bucket 0
    assert (s[1:] >= SPECIAL).all() and PAD not in s
    assert len(seqs[HUB]) == 101 <= MAX_LEN            # every bad address pays the hub
    monkeypatch.setattr(tok, "MAX_LEN", 21)
    hub = encode(events(sample), counterparty_types(sample))[HUB]
    full = seqs[HUB]
    assert len(hub) == 21 and (hub[1:] == full[-20:]).all()   # the latest 20 events kept
    exch = seqs[BAD[0]][:, FIELDS.index("cp_type")]
    assert set(exch[1:]) <= {SPECIAL + 0, SPECIAL + 1}  # eoa senders, the hub is a contract


def test_buckets():
    assert amount_bucket(None) == 0 and amount_bucket(1.0) == 8 and amount_bucket(1e40) == 31
    assert gap_bucket(None) == 0 and gap_bucket(0) == 1 and gap_bucket(3600) == 12


def test_baseline_features_one_row_per_address(sample):
    feats = table(events(sample), counterparty_types(sample))
    row = feats.filter(pl.col("address") == BAD[0]).row(0, named=True)
    assert list(feats.columns) == ["address", *NAMES]
    assert (row["n_events"], row["n_in"], row["n_out"]) == (10, 5, 5)
    assert row["log_usd_in"] > 10 and row["log_eth_in"] == 0
    good = feats.filter(pl.col("address") == addr(100)).row(0, named=True)
    assert 0 <= good["share_cp_exchange"] <= 1


def test_graph_score_is_the_value_share_with_bad_addresses(sample):
    g = graph_scores(sample.transfers, set(BAD))
    assert g[HUB] == 1.0 and g.get(EXCHANGE, 0.0) == 0.0


def test_rank_and_recall():
    assert np.allclose(rank01(np.array([3.0, 1.0, 1.0])), [1.0, 0.25, 0.25])
    assert recall_at(np.array([0.9, 0.1, 0.8]), ["a", "b", "c"], {"a", "b"}, k=2) == 0.5
