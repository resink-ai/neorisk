"""Cheap, machine-independent file fingerprints.

Sampled ("s"): size plus blake2b of the head, middle and tail chunks. Reads a few MiB however
large the file is, but misses a same-size edit that falls between the samples.
Full ("f"): size plus blake2b of the whole file.
"""

import hashlib
from pathlib import Path

CHUNK = 1 << 20


def fingerprint(path: Path, *, full: bool = False) -> str:
    size = path.stat().st_size
    h = hashlib.blake2b(digest_size=16)
    with path.open("rb") as f:
        if full or size <= 3 * CHUNK:
            while block := f.read(CHUNK):
                h.update(block)
        else:
            for offset in (0, (size - CHUNK) // 2, size - CHUNK):
                f.seek(offset)
                h.update(f.read(CHUNK))
    # a small file read in full is hashed identically in both modes, so label by what was asked
    return f"{'f' if full else 's'}:{size}:{h.hexdigest()}"


def same_mode(a: str, b: str) -> bool:
    return a[0] == b[0]


def mode_is_full(fp: str) -> bool:
    return fp[0] == "f"
