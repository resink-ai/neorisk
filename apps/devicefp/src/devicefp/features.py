"""Profiles -> hashed tokens, and the drift augmentation used in training.

Every field value (or set item) becomes one token: a stable hash of "field=value" into a shared
table of BUCKETS rows. A value never seen in training still gets a fixed vector, so two
profiles that share a rare value (an IP hash, a canvas hash) still look alike to the encoder.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from devicefp.profiles import Profiles

BUCKETS = 1 << 18
EMPTY = "\x00empty"       # a set field with no items
MASK = 0                  # bucket 0 is reserved for a masked field


def bucket(field: str, value: str) -> int:
    h = hashlib.blake2b(f"{field}={value}".encode(), digest_size=8).digest()
    return 1 + int.from_bytes(h, "little") % (BUCKETS - 1)


@dataclass
class Encoded:
    """rows[i][f] is the token array of field f of profile i."""
    rows: list[list[np.ndarray]]
    fields: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.rows)


def encode(p: Profiles) -> Encoded:
    cache: dict[tuple[str, str], int] = {}

    def tok(field: str, value: str) -> int:
        k = (field, value)
        if k not in cache:
            cache[k] = bucket(field, value)
        return cache[k]

    cols = [p.table[f.name].to_list() for f in p.fields]
    rows: list[list[np.ndarray]] = []
    for i in range(len(p)):
        row = []
        for f, col in zip(p.fields, cols, strict=True):
            v = col[i]
            if f.kind == "set":
                items = sorted(set(v or [])) or [EMPTY]
                row.append(np.array([tok(f.name, x) for x in items], dtype=np.int64))
            else:
                row.append(np.array([tok(f.name, "" if v is None else str(v))], dtype=np.int64))
        rows.append(row)
    return Encoded(rows, tuple(f.name for f in p.fields))


@dataclass
class Drift:
    """How a training view is perturbed, to look like the same device seen later."""
    swap: float = 0.15        # a field takes the value of the same field in another profile
    mask: float = 0.10        # a field is hidden
    drop_item: float = 0.10   # each set item is dropped
    add_items: float = 0.10   # a set field also gains a few items from another profile
    spoof: float = 0.0        # all SPOOFABLE fields jointly take another profile's values, like
                              # a user-agent switcher (they are the ones such tools rewrite)
    swap_by_field: tuple[float, ...] | None = None   # per-field swap rate; replaces `swap`


SPOOFABLE = ("user_agent", "ua_words", "platform", "os", "browser", "vendor", "app_version",
             "oscpu")


def augment(row: list[np.ndarray], pool: Encoded, rng: np.random.Generator,
            d: Drift) -> list[np.ndarray]:
    out = []
    spoofed = None
    if d.spoof and rng.random() < d.spoof:
        donor = pool.rows[rng.integers(len(pool))]
        spoofed = {f for f, name in enumerate(pool.fields) if name in SPOOFABLE}
    for f, toks in enumerate(row):
        if spoofed is not None and f in spoofed:
            out.append(donor[f])
            continue
        r = rng.random()
        if r < d.mask:
            out.append(np.array([MASK], dtype=np.int64))
            continue
        swap = d.swap if d.swap_by_field is None else d.swap_by_field[f]
        if r < d.mask + swap:
            toks = pool.rows[rng.integers(len(pool))][f]
        if len(toks) > 1:
            keep = rng.random(len(toks)) >= d.drop_item
            toks = toks[keep] if keep.any() else toks[:1]
            if rng.random() < d.add_items:
                other = pool.rows[rng.integers(len(pool))][f]
                toks = np.union1d(toks, rng.choice(other, size=min(3, len(other)),
                                                   replace=False))
        out.append(toks)
    return out
