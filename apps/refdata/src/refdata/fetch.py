"""Download the Spider2-lite local SQLite databases (one zip on Google Drive, linked from
`spider2-lite/README.md` in xlang-ai/Spider2) into `data/spider2/`, verified by sha256.
"""

from __future__ import annotations

import hashlib
import urllib.request
import zipfile
from pathlib import Path

ZIP_URL = ("https://drive.usercontent.google.com/download?id=1coEVsCZq-Xvj9p2TnhBFoFTsY-UoYGmG"
           "&export=download&authuser=0&confirm=t")
ZIP_SHA256 = "d56acf7c9d89be4bdf1f4f1281f4a03d91735f1858f6d6d0cfe0f9d562e3a94f"
DATA = Path("data/spider2")
EXPECTED = [
    "AdventureWorks.sqlite", "Airlines.sqlite", "Baseball.sqlite", "BowlingLeague.sqlite",
    "Brazilian_E_Commerce.sqlite", "California_Traffic_Collision.sqlite", "Db-IMDB.sqlite",
    "EU_soccer.sqlite", "E_commerce.sqlite", "EntertainmentAgency.sqlite", "IPL.sqlite",
    "Pagila.sqlite", "WWE.sqlite", "bank_sales_trading.sqlite", "chinook.sqlite",
    "city_legislation.sqlite", "complex_oracle.sqlite", "delivery_center.sqlite",
    "education_business.sqlite", "electronic_sales.sqlite", "f1.sqlite", "imdb_movies.sqlite",
    "log.sqlite", "modern_data.sqlite", "music.sqlite", "northwind.sqlite", "oracle_sql.sqlite",
    "school_scheduling.sqlite", "sqlite-sakila.sqlite", "stacking.sqlite",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, sha256: str) -> None:
    actual = _sha256(path)
    if actual != sha256:
        raise ValueError(f"{path}: sha256 {actual}, expected {sha256}")


def unpack(zip_path: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.startswith("__MACOSX/") or not name.endswith(".sqlite"):
                continue
            target = dest / Path(name).name
            with z.open(name) as src, target.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            out.append(target)
    return sorted(out)


def fetch(dest: Path = DATA, *, force: bool = False) -> list[Path]:
    """Download, verify and unpack the zip, unless every expected file is already there."""
    have = [dest / n for n in EXPECTED]
    if not force and all(p.exists() for p in have):
        return have
    dest.mkdir(parents=True, exist_ok=True)
    part = dest / "localdb.zip.part"
    with urllib.request.urlopen(ZIP_URL) as r, part.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    verify(part, ZIP_SHA256)
    zip_path = part.rename(dest / "localdb.zip")
    unpack(zip_path, dest)
    zip_path.unlink()
    missing = [p.name for p in have if not p.exists()]
    if missing:
        raise ValueError(f"the zip lacks {missing}")
    return have
