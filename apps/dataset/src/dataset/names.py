"""Data names: `<dataset>/<version>[/<path>]`, resolved against one data root.

The root is `$NEORISK_DATA_ROOT` (relative to the working directory), else
`<repo>/data/datasets`. Every path to a data file goes through `resolve`, so a remote root
(S3, a network file system) later changes this one place.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATASET = re.compile(r"[a-z0-9][a-z0-9_-]*")
VERSION = re.compile(r"v[1-9][0-9]*")


class BadName(ValueError):
    pass


def data_root() -> Path:
    env = os.environ.get("NEORISK_DATA_ROOT")
    return Path(env).resolve() if env else REPO / "data" / "datasets"


def resolve(name: str) -> Path:
    if not name or "\\" in name or name.startswith("/"):
        raise BadName(f"bad data name {name!r}: want <dataset>/<version>[/<path>]")
    parts = name.split("/")
    if (len(parts) < 2 or not DATASET.fullmatch(parts[0]) or not VERSION.fullmatch(parts[1])
            or any(p in ("", ".", "..") for p in parts)):
        raise BadName(f"bad data name {name!r}: want <dataset>/<version>[/<path>], with a "
                      f"lower-case dataset and a version v1, v2, ...")
    return data_root().joinpath(*parts)
