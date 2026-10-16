"""`run_stats.json`: timings, rates, peak RSS, rounds and engine counters (not part of replay
identity)."""

from __future__ import annotations

import json
import os
import platform
import resource
import sys
from pathlib import Path
from typing import Any


def peak_rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss * 1024)


def machine() -> dict[str, Any]:
    return {"arch": platform.machine(), "cpus": os.cpu_count(),
            "ram_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")}


def write_run_stats(run_dir: Path, stats: dict[str, Any]) -> Path:
    path = Path(run_dir) / "run_stats.json"
    path.write_text(json.dumps(stats, sort_keys=True, indent=2) + "\n")
    return path
