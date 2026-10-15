import numpy as np

# positions of the 32 hex digits in the canonical 8-4-4-4-12 layout (the rest are dashes)
_HEX_POS = np.r_[0:8, 9:13, 14:18, 19:23, 24:36]


def make_uuids(n: int, rng: np.random.Generator) -> list[str]:
    """Deterministic version-4 UUID strings drawn from ``rng``.

    Equivalent to ``str(uuid.UUID(bytes=b, version=4))`` for consecutive 16-byte chunks of
    ``rng.bytes(16 * n)``, but vectorized: version/variant bits are set with numpy and all
    ids are hex-encoded in a single pass.
    """
    if n == 0:
        return []
    raw = np.frombuffer(rng.bytes(16 * n), dtype=np.uint8).reshape(n, 16).copy()
    raw[:, 6] = (raw[:, 6] & 0x0F) | 0x40  # version 4
    raw[:, 8] = (raw[:, 8] & 0x3F) | 0x80  # RFC 4122 variant
    hexed = np.frombuffer(raw.tobytes().hex().encode("ascii"), dtype=np.uint8).reshape(n, 32)
    out = np.full((n, 36), ord("-"), dtype=np.uint8)
    out[:, _HEX_POS] = hexed
    return out.view("S36").ravel().astype("U36").tolist()
