"""A small synthetic sample in eth-collect's shape: bad addresses take large stablecoin
deposits and forward them fast to one hub; random ones send small ETH to many places."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest
import torch

from ethmodel.data import Sample

# The full suite loads three OpenMP runtimes (torch's, sklearn's, xgboost's); a multi-threaded
# torch kernel then deadlocks in an OpenMP barrier. Toy-sized tensors need no threads.
torch.set_num_threads(1)

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def addr(i: int) -> str:
    return f"0x{i:040x}"


BAD = [addr(i) for i in range(1, 21)]
GOOD = [addr(i) for i in range(100, 160)]
HUB, EXCHANGE = addr(9000), addr(9001)


def transfer(i, a, b, ts, *, eth=None, usd=None):
    return {"tx_hash": f"0x{i:064x}" if eth is not None else None, "block_number": i,
            "log_index": -1 if eth is not None else 0, "ts": ts, "from_address": a,
            "to_address": b, "kind": "external" if eth is not None else "erc20",
            "asset": "ETH" if eth is not None else USDT,
            "asset_symbol": "ETH" if eth is not None else "USDT",
            "amount": eth if eth is not None else usd, "decimals": 18 if eth is not None else 6,
            "usd_approx": usd, "method_id": None, "status": 1, "source": "aws-public"}


def build() -> Sample:
    rng = random.Random(0)
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    rows, i = [], 0
    for a in BAD:
        for k in range(5):
            ts = t0 + timedelta(days=rng.randrange(150), seconds=k)
            rows.append(transfer(i := i + 1, addr(5000 + rng.randrange(50)), a, ts,
                                 usd=rng.uniform(5e4, 9e4)))
            rows.append(transfer(i := i + 1, a, HUB, ts + timedelta(minutes=3),
                                 usd=rng.uniform(5e4, 9e4)))
    for a in GOOD:
        for _ in range(5):
            ts = t0 + timedelta(days=rng.randrange(150), hours=rng.randrange(24))
            rows.append(transfer(i := i + 1, a, rng.choice([EXCHANGE, addr(7000 + i)]), ts,
                                 eth=rng.uniform(0.01, 0.5)))
    transfers = pl.DataFrame(rows, schema_overrides={"ts": pl.Datetime("us", "UTC")},
                             infer_schema_length=None)
    reasons = {**{a: "seed" for a in BAD}, **{a: "random" for a in GOOD}}
    others = (set(transfers["from_address"]) | set(transfers["to_address"])) - set(reasons)
    reasons |= {a: "counterparty" for a in others}
    addresses = pl.DataFrame([{"address": a, "is_contract": a == HUB, "first_seen": None,
                               "sample_reason": r, "source": "sample"}
                              for a, r in sorted(reasons.items())],
                             schema_overrides={"first_seen": pl.Datetime("us", "UTC")})
    labels = [{"address": a, "label_kind": "frozen" if j < 14 else "phishing", "is_risk": True,
               "source": "test", "source_ref": None, "trust": 0.9 if j < 14 else 0.6,
               "observed_at": date(2026, 10, 1), "date_known": j < 14}
              for j, a in enumerate(BAD)]
    labels.append({"address": EXCHANGE, "label_kind": "exchange", "is_risk": False,
                   "source": "test", "source_ref": None, "trust": 0.6,
                   "observed_at": date(2026, 10, 1), "date_known": False})
    return Sample(addresses, transfers, pl.DataFrame(labels))


@pytest.fixture
def sample() -> Sample:
    return build()


@pytest.fixture
def toy_dir(tmp_path, sample):
    folder = tmp_path / "toy"
    folder.mkdir()
    sample.addresses.write_parquet(folder / "addresses.parquet")
    sample.transfers.write_parquet(folder / "transfers.parquet")
    sample.labels.write_parquet(folder / "labels.parquet")
    return folder
