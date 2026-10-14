import uuid

import numpy as np


def make_uuids(n: int, rng: np.random.Generator) -> list[str]:
    """Deterministic version-4 UUID strings drawn from ``rng``."""
    raw = rng.bytes(16 * n)
    return [str(uuid.UUID(bytes=raw[i * 16 : (i + 1) * 16], version=4)) for i in range(n)]
