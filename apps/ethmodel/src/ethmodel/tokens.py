"""Each address's events -> a sequence of tokens, one per transfer, with [CLS] in front.

A token is a vector of field ids; its embedding is the sum of the field embeddings. Ids 0-2
are special in every field (pad, mask, cls); real values start at 3. Raw addresses never
enter: the counterparty is a hashed bucket, so two addresses that share counterparties look
alike.
"""

from __future__ import annotations

import math
import zlib

import numpy as np
import polars as pl

PAD, MASK, CLS = 0, 1, 2
SPECIAL = 3
DIRECTIONS = ("in", "out", "self")
KINDS = ("external", "internal", "erc20")
ASSETS = ("eth", "stable", "token")
CP_TYPES = ("eoa", "contract", "exchange", "bridge", "mixer", "dex", "unknown")
SIZES = {"direction": 3, "kind": 3, "asset": 3, "amount": 32, "gap": 32, "cp_type": 7,
         "method": 1024, "cp_id": 65536}
FIELDS = tuple(SIZES)
# what masked event modeling predicts back (the plan's amount, timing, kind, direction, type)
PREDICT = ("direction", "kind", "amount", "gap", "cp_type")
MAX_LEN = 128   # tokens, [CLS] included


def amount_bucket(amount: float | None) -> int:
    """One bucket per decade from 1e-8 up; non-token assets are in whole units, other tokens
    in raw units, so the asset field tells the two scales apart."""
    if not amount or amount <= 0:
        return 0
    return min(max(math.floor(math.log10(amount)) + 8, 0), 31)


def gap_bucket(seconds: float | None) -> int:
    """0 for an address's first event, else 1 + log2 of the seconds since the previous one."""
    if seconds is None:
        return 0
    return min(math.floor(math.log2(seconds + 1)), 30) + 1


def method_bucket(method_id: str | None) -> int:
    return 0 if not method_id else zlib.crc32(method_id.encode()) % (SIZES["method"] - 1) + 1


def cp_bucket(address: str | None) -> int:
    return 0 if not address else zlib.crc32(address.encode()) % SIZES["cp_id"]


def encode(ev: pl.DataFrame, cp_types: dict[str, str]) -> dict[str, np.ndarray]:
    """Events (from `data.events`, time-ordered) -> address -> int array [len, fields].
    The latest MAX_LEN - 1 events are kept."""
    out = {}
    for (owner,), part in ev.group_by("owner", maintain_order=True):
        # gaps come from the whole history, so the first kept event still knows its predecessor
        prevs = [None, *part["ts"].to_list()[:-1]][-(MAX_LEN - 1):]
        rows = part.tail(MAX_LEN - 1).to_dicts()
        seq = [[CLS] * len(FIELDS)]
        for r, prev in zip(rows, prevs, strict=True):
            gap = None if prev is None else (r["ts"] - prev).total_seconds()
            cp = r["counterparty"]
            vals = {"direction": DIRECTIONS.index(r["direction"]),
                    "kind": KINDS.index(r["kind"]), "asset": ASSETS.index(r["asset_class"]),
                    "amount": amount_bucket(r["amount"]), "gap": gap_bucket(gap),
                    "cp_type": CP_TYPES.index(cp_types.get(cp, "unknown")),
                    "method": method_bucket(r["method_id"]), "cp_id": cp_bucket(cp)}
            seq.append([vals[f] + SPECIAL for f in FIELDS])
        out[owner] = np.asarray(seq, dtype=np.int64)
    return out


def pad(seqs: list[np.ndarray]) -> np.ndarray:
    """A batch [n, longest, fields], padded with PAD."""
    width = max(len(s) for s in seqs)
    batch = np.full((len(seqs), width, len(FIELDS)), PAD, dtype=np.int64)
    for i, s in enumerate(seqs):
        batch[i, : len(s)] = s
    return batch
