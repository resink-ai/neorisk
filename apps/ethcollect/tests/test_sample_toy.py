"""The toy recipe end to end, with fake connectors standing in for the network."""

import argparse
import json
from datetime import UTC, date, datetime, timedelta

import polars as pl

from ethcollect import connectors, sample, tables
from ethcollect.cli import build_parser
from ethcollect.status import report

UNTIL = date(2026, 10, 1)


def addr(i: int) -> str:
    return f"0x{i:040x}"


SEED_POOL = [addr(i) for i in range(1, 41)]  # labeled; odd ones are active in the window
RANDOM_POOL = [addr(i) for i in range(1000, 1060)]
HUB = addr(9999)  # a counterparty everyone touches


def fake_run(source: str, ns: argparse.Namespace) -> bool:
    out = ns.out
    if source == "ofac":
        rows = tables.label_rows(SEED_POOL, kind="sanctioned", source="ofac", trust="high",
                                 observed_at=UNTIL - timedelta(days=30))
        tables.write(out, "labels", "ofac", tables.frame("labels", rows))
    elif source == "aws-public" and ns.mode == "scan":
        active = [a for a in SEED_POOL if int(a, 16) % 2] + RANDOM_POOL
        rows = [{"tx_hash": None, "block_number": int(a, 16), "log_index": k,
                 "ts": datetime(2026, 9, 1 + k, tzinfo=UTC), "from_address": a,
                 "to_address": HUB, "kind": "erc20", "asset": HUB, "asset_symbol": None,
                 "amount": 1.0, "decimals": None, "usd_approx": None, "method_id": None,
                 "status": 1, "source": "aws-public"} for a in active for k in range(ns.cap)]
        tables.write(out, "transfers", "aws-public", tables.frame("transfers", rows))
        rows = [{"address": a, "is_contract": None, "first_seen": None,
                 "sample_reason": "random", "source": "aws-public"} for a in RANDOM_POOL]
        tables.write(out, "addresses", "aws-public", tables.frame("addresses", rows))
    elif source == "aws-public":
        rows = [{"address": a, "is_contract": None, "first_seen": None,
                 "sample_reason": "random", "source": "aws-public"} for a in RANDOM_POOL]
        tables.write(out, "addresses", "aws-public", tables.frame("addresses", rows))
    elif source == "blockscout":
        rows = []
        for a in ns.addresses.read_text().split():
            i = int(a, 16)
            if a in SEED_POOL and i % 2 == 0:
                continue  # inactive seed: no history
            for k in range(8):  # more than the cap of 5
                rows.append({
                    "tx_hash": f"0x{i:x}{k:02x}", "log_index": -1, "block_number": k,
                    "ts": datetime(2026, 9, 1 + k, tzinfo=UTC), "from_address": a,
                    "to_address": HUB, "kind": "external", "asset": "ETH",
                    "asset_symbol": "ETH", "amount": 1.0, "decimals": 18, "usd_approx": None,
                    "method_id": None, "status": 1, "source": "blockscout"})
        tables.append(out, "transfers", "blockscout", tables.frame("transfers", rows))
    elif source == "rpc":
        todo = ns.addresses.read_text().split()
        rows = [{"address": a, "is_contract": a == HUB, "first_seen": None,
                 "sample_reason": None, "source": "rpc"} for a in todo]
        tables.write(out, "addresses", "rpc", tables.frame("addresses", rows))
    return True


def test_toy_recipe_builds_a_capped_seeded_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(connectors, "label_sources", lambda: ["ofac"])
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    args = build_parser().parse_args([
        "sample", "toy", "--out", str(tmp_path), "--until", UNTIL.isoformat(),
        "--seeds", "10", "--background", "20", "--cap", "5", "--history", "blockscout"])
    assert sample.toy(args, fake_run) == 0

    toy = tmp_path / "samples" / "toy"
    ad = pl.read_parquet(toy / "addresses.parquet")
    tr = pl.read_parquet(toy / "transfers.parquet")
    manifest = json.loads((toy / "manifest.json").read_text())

    seeds = ad.filter(pl.col("sample_reason") == "seed")["address"].to_list()
    assert len(seeds) == 10 and all(int(a, 16) % 2 == 1 for a in seeds)  # only active seeds
    assert ad.filter(pl.col("sample_reason") == "random").height == 20
    assert ad.filter(pl.col("sample_reason") == "counterparty")["address"].to_list() == [HUB]
    assert ad.filter(pl.col("address") == HUB)["is_contract"].item() is True
    per = tr.group_by("from_address").len()["len"]
    assert per.max() == 5 and tr.height == 30 * 5
    assert manifest["history_source"] == "blockscout" and manifest["seeds"] == 10
    assert pl.read_parquet(toy / "labels.parquet")["address"].n_unique() == 10
    assert not (toy / "batch.txt").exists()

    text = report(tmp_path)
    assert "risk-labeled sampled addresses: 10" in text
    assert "transfers after a label's observed_at: 50" in text  # Sep 1-8 > Sep 1 flag date


def test_toy_without_a_key_scans_aws_days(tmp_path, monkeypatch):
    monkeypatch.setattr(connectors, "label_sources", lambda: ["ofac"])
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    calls = []

    def spy(source, ns):
        calls.append(source)
        return fake_run(source, ns)

    args = build_parser().parse_args([
        "sample", "toy", "--out", str(tmp_path), "--until", UNTIL.isoformat(),
        "--seeds", "10", "--background", "20", "--cap", "5"])
    assert sample.toy(args, spy) == 0
    assert "blockscout" not in calls and "etherscan" not in calls

    toy = tmp_path / "samples" / "toy"
    ad = pl.read_parquet(toy / "addresses.parquet")
    tr = pl.read_parquet(toy / "transfers.parquet")
    manifest = json.loads((toy / "manifest.json").read_text())
    seeds = ad.filter(pl.col("sample_reason") == "seed")["address"].to_list()
    assert len(seeds) == 10 and all(int(a, 16) % 2 == 1 for a in seeds)
    assert ad.filter(pl.col("sample_reason") == "random").height == 20
    assert tr.height == 30 * 5 and tr["tx_hash"].null_count() == tr.height
    assert manifest["history_source"] == "aws-scan" and manifest["scan_days"] == 30
